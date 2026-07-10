#!/usr/bin/env python3
"""Validate the integration's RELEASE_DELAY against DWD OpenData reality.

Each DWD product declares a ``RELEASE_DELAY`` — how long after the nominal
product time a file is expected to appear on OpenData. The coordinator waits
exactly that long before fetching (``_get_latest_release``), so if DWD's real
publication lag drifts away from the configured value the integration either
polls too early (repeated 404 + fast-poll churn) or too late (needlessly stale
sensors).

This script measures the *observed* availability delay for each probeable
product and checks it does not deviate too far from the configured constant.
It is HA-free: the configured constants are read straight from the integration
source with ``ast`` (single source of truth, no ``homeassistant`` import), and
DWD is probed with ``requests``.

How the delay is measured
-------------------------
For a product with interval ``I`` and offset ``O`` the releases occur at
timestamps ``k*I + O``. We probe OpenData to find the *frontier* — the newest
release ``F`` whose file exists while ``F + I`` does not. That alone bounds the
true delay ``D`` to the window ``(now - F - I, now - F]`` (width ``I``).

When the *next* release is due to appear within ``--max-poll-wait``, we poll
until it shows up and record the exact delay ``appearance - timestamp``. That
removes the interval-sized uncertainty and, for the fast 5-minute RS cadence,
lets us average several consecutive appearances — the "average timedelta" the
check is built around. Otherwise we fall back to the window midpoint with an
uncertainty of ``I/2``.

A product is flagged when ``|configured - observed| > uncertainty + grace``.
The ``uncertainty`` term makes coarse (window-only) estimates unable to raise a
false alarm from the measurement window alone; exact samples get the tight
``grace`` tolerance.

Exit status: ``0`` all products within tolerance, ``1`` at least one drifted,
``2`` a product could not be measured (nothing downloadable / network error).

Usage::

    uv run --group unit-test python scripts/check_release_delay.py
    uv run --group unit-test python scripts/check_release_delay.py --products rs
    uv run --group unit-test python scripts/check_release_delay.py --no-poll
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

UTC = timezone.utc

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATION = _REPO_ROOT / "custom_components" / "dwd_precipitation"

_OPENDATA = "https://opendata.dwd.de/weather/radar"

RELEASE_KEYS = ("RELEASE_INTERVAL", "RELEASE_DELAY", "RELEASE_OFFSET")


# ---------------------------------------------------------------------------
# Configured-timing extraction (HA-free, straight from the integration source)
# ---------------------------------------------------------------------------

def _timedelta_from_call(node: ast.Call) -> timedelta:
    """Build a timedelta from a literal ``timedelta(...)`` AST call."""
    args = []
    for a in node.args:
        if not isinstance(a, ast.Constant):
            raise ValueError("non-literal positional arg in timedelta(...)")
        args.append(a.value)
    kwargs = {}
    for kw in node.keywords:
        if kw.arg is None or not isinstance(kw.value, ast.Constant):
            raise ValueError("non-literal keyword arg in timedelta(...)")
        kwargs[kw.arg] = kw.value.value
    return timedelta(*args, **kwargs)


def _is_timedelta_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "timedelta") or (
        isinstance(func, ast.Attribute) and func.attr == "timedelta"
    )


def _parse_classes(path: Path) -> dict[str, tuple[list[str], dict[str, timedelta]]]:
    """Map every class in ``path`` to (base names, {RELEASE_*: timedelta})."""
    tree = ast.parse(path.read_text())
    classes: dict[str, tuple[list[str], dict[str, timedelta]]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        bases = [
            b.id if isinstance(b, ast.Name) else b.attr
            for b in node.bases
            if isinstance(b, (ast.Name, ast.Attribute))
        ]

        attrs: dict[str, timedelta] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign):
                targets, value = [stmt.target], stmt.value
            elif isinstance(stmt, ast.Assign):
                targets, value = stmt.targets, stmt.value
            else:
                continue
            if value is None or not _is_timedelta_call(value):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in RELEASE_KEYS:
                    attrs[target.id] = _timedelta_from_call(value)

        classes[node.name] = (bases, attrs)

    return classes


def _load_registry() -> dict[str, tuple[list[str], dict[str, timedelta]]]:
    """Merge the class tables from coordinator.py (base) and products.py."""
    registry: dict[str, tuple[list[str], dict[str, timedelta]]] = {}
    for name in ("coordinator.py", "products.py"):
        registry.update(_parse_classes(_INTEGRATION / name))
    return registry


def extract_timing(
    class_name: str,
    registry: dict[str, tuple[list[str], dict[str, timedelta]]] | None = None,
) -> dict[str, timedelta]:
    """Resolve the three RELEASE_* constants for ``class_name`` across bases.

    Walks the (single-inheritance) base chain depth-first, first base winning —
    the same precedence Python's MRO gives this linear hierarchy — so an
    overridden constant shadows the inherited default.
    """
    if registry is None:
        registry = _load_registry()

    resolved: dict[str, timedelta] = {}
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name not in registry:
            return
        seen.add(name)
        bases, attrs = registry[name]
        for key, value in attrs.items():
            resolved.setdefault(key, value)
        for base in bases:
            visit(base)

    visit(class_name)

    missing = [k for k in RELEASE_KEYS if k not in resolved]
    if missing:
        raise ValueError(f"{class_name}: could not resolve {missing}")
    return resolved


# ---------------------------------------------------------------------------
# Release schedule
# ---------------------------------------------------------------------------

def previous_release(now: datetime, interval: timedelta, offset: timedelta) -> datetime:
    """Most recent scheduled release timestamp at or before ``now``.

    Anchored to the Unix epoch. Safe for the probeable products (rs/rw/sf) whose
    intervals divide a day, which is exactly when epoch- and civil-anchoring
    agree — matching the integration's ``get_previous_multiple``.
    """
    interval_s = interval.total_seconds()
    base = offset.total_seconds() % interval_s
    t = now.timestamp()
    k = (t - base) // interval_s
    return datetime.fromtimestamp(k * interval_s + base, tz=UTC)


# ---------------------------------------------------------------------------
# Product probe specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductSpec:
    """Everything needed to probe one product's availability."""

    key: str
    class_name: str
    url_for: Callable[[datetime], str]


PRODUCTS: dict[str, ProductSpec] = {
    "rs": ProductSpec(
        "rs",
        "RadvorRS",
        lambda ts: f"{_OPENDATA}/composite/rs/composite_rs_{ts.strftime('%Y%m%d_%H%M')}.tar",
    ),
    "rw": ProductSpec(
        "rw",
        "RadolanRW",
        lambda ts: f"{_OPENDATA}/radolan/rw/raa01-rw_10000-{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2",
    ),
    "sf": ProductSpec(
        "sf",
        "RadolanSF",
        lambda ts: f"{_OPENDATA}/radolan/sf/raa01-sf_10000-{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2",
    ),
}


def http_available(url: str, timeout: float = 60.0, attempts: int = 3) -> bool:
    """Return True if ``url`` responds 2xx. Body is never downloaded."""
    import requests  # imported lazily so the module loads without the dep

    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, stream=True, timeout=timeout)
            try:
                if resp.status_code == 404:
                    return False
                resp.raise_for_status()
                return True
            finally:
                resp.close()
        except requests.HTTPError:
            raise
        except requests.RequestException as err:
            last_err = err
            time.sleep((attempt + 1) * 0.5)
    raise RuntimeError(f"network error probing {url}: {last_err}")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """Outcome of measuring one product's availability delay."""

    key: str
    class_name: str
    configured: timedelta
    interval: timedelta
    observed: timedelta | None = None
    uncertainty: timedelta = timedelta()
    window: tuple[timedelta, timedelta] | None = None
    exact_samples: list[timedelta] = field(default_factory=list)
    frontier: datetime | None = None
    error: str | None = None

    @property
    def deviation(self) -> timedelta | None:
        if self.observed is None:
            return None
        return abs(self.configured - self.observed)

    def tolerance(self, grace: timedelta) -> timedelta:
        return self.uncertainty + grace

    def status(self, grace: timedelta) -> str:
        if self.error is not None or self.observed is None:
            return "ERROR"
        return "OK" if self.deviation <= self.tolerance(grace) else "DRIFT"


def find_frontier(
    url_for: Callable[[datetime], str],
    start: datetime,
    interval: timedelta,
    available: Callable[[str], bool],
    max_steps: int = 24,
) -> datetime:
    """Return the newest available release ``F`` with ``F + interval`` absent.

    ``start`` is the integration's expected-latest release; we walk back if DWD
    is slower than configured and forward if it is faster.
    """
    ts = start
    steps = 0
    while not available(url_for(ts)):
        ts -= interval
        steps += 1
        if steps > max_steps:
            raise RuntimeError("no available release found near the expected slot")

    steps = 0
    while available(url_for(ts + interval)):
        ts += interval
        steps += 1
        if steps > max_steps:
            raise RuntimeError("frontier kept advancing; interval/offset likely wrong")
    return ts


def measure(
    spec: ProductSpec,
    configured: dict[str, timedelta],
    now: datetime,
    *,
    available: Callable[[str], bool] = http_available,
    poll: bool = True,
    max_poll_wait: timedelta = timedelta(minutes=11),
    poll_interval: timedelta = timedelta(seconds=20),
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    wall_now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Measurement:
    """Measure the observed availability delay for one product."""
    interval = configured["RELEASE_INTERVAL"]
    offset = configured["RELEASE_OFFSET"]
    delay = configured["RELEASE_DELAY"]
    m = Measurement(spec.key, spec.class_name, delay, interval)

    try:
        start = previous_release(now - delay, interval, offset)
        frontier = find_frontier(spec.url_for, start, interval, available)
        m.frontier = frontier

        if poll:
            m.exact_samples = _capture_exact(
                spec, frontier, interval, delay, now, available,
                max_poll_wait, poll_interval, sleep, monotonic, wall_now,
            )

        if m.exact_samples:
            total = sum(m.exact_samples, timedelta())
            m.observed = total / len(m.exact_samples)
            m.uncertainty = timedelta()
        else:
            lower = now - (frontier + interval)
            upper = now - frontier
            m.window = (lower, upper)
            m.observed = (lower + upper) / 2
            m.uncertainty = interval / 2
    except Exception as err:  # network / logic — reported, never crashes the run
        m.error = str(err)

    return m


def _capture_exact(
    spec: ProductSpec,
    frontier: datetime,
    interval: timedelta,
    delay: timedelta,
    now: datetime,
    available: Callable[[str], bool],
    max_poll_wait: timedelta,
    poll_interval: timedelta,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    wall_now: Callable[[], datetime],
) -> list[timedelta]:
    """Poll for imminent releases to pin the exact delay, averaging several.

    Only polls when the next release is expected to land within
    ``max_poll_wait``; otherwise returns no samples and the caller falls back to
    the window estimate.
    """
    samples: list[timedelta] = []
    deadline = monotonic() + max_poll_wait.total_seconds()
    ts_next = frontier + interval

    while True:
        expected = ts_next + delay
        wait_left = deadline - monotonic()
        # Skip if the appearance is further out than we are willing to wait.
        if (expected - now).total_seconds() > wait_left:
            break

        appeared = False
        while monotonic() < deadline:
            if available(spec.url_for(ts_next)):
                appeared = True
                break
            sleep(poll_interval.total_seconds())

        if not appeared:
            break

        samples.append(wall_now() - ts_next)
        ts_next += interval

    return samples


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(td: timedelta | None) -> str:
    if td is None:
        return "—"
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 60}m{total % 60:02d}s"


def _report_lines(measurements: list[Measurement], grace: timedelta) -> list[str]:
    header = f"{'product':<8}{'status':<8}{'configured':>12}{'observed':>12}{'deviation':>12}{'tolerance':>12}"
    lines = [header, "-" * len(header)]
    for m in measurements:
        lines.append(
            f"{m.key:<8}{m.status(grace):<8}"
            f"{_fmt(m.configured):>12}{_fmt(m.observed):>12}"
            f"{_fmt(m.deviation):>12}{_fmt(m.tolerance(grace)):>12}"
        )
        detail = []
        if m.error:
            detail.append(f"error: {m.error}")
        elif m.exact_samples:
            detail.append(
                f"{len(m.exact_samples)} exact sample(s): "
                + ", ".join(_fmt(s) for s in m.exact_samples)
            )
        elif m.window:
            detail.append(
                f"window {_fmt(m.window[0])}..{_fmt(m.window[1])} "
                f"(frontier {m.frontier:%Y-%m-%d %H:%M UTC})"
            )
        if detail:
            lines.append(f"         └ {' | '.join(detail)}")
    return lines


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("## DWD release-delay check\n\n```\n" + text + "\n```\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--products", nargs="+", choices=list(PRODUCTS), default=list(PRODUCTS),
        help="products to check (default: all probeable products)",
    )
    parser.add_argument(
        "--grace", type=float, default=5.0,
        help="tolerance in minutes on top of the measurement uncertainty (default: 5)",
    )
    parser.add_argument(
        "--no-poll", action="store_true",
        help="skip exact-appearance polling; use the frontier window only",
    )
    parser.add_argument(
        "--max-poll-wait", type=float, default=11.0,
        help="max minutes to poll for an imminent release (default: 11)",
    )
    args = parser.parse_args(argv)

    grace = timedelta(minutes=args.grace)
    registry = _load_registry()
    now = datetime.now(UTC)

    measurements: list[Measurement] = []
    for key in args.products:
        spec = PRODUCTS[key]
        configured = extract_timing(spec.class_name, registry)
        measurements.append(
            measure(
                spec, configured, now,
                poll=not args.no_poll,
                max_poll_wait=timedelta(minutes=args.max_poll_wait),
            )
        )

    report = "\n".join(_report_lines(measurements, grace))
    print(report)
    _write_summary(report)

    statuses = [m.status(grace) for m in measurements]
    if "ERROR" in statuses:
        return 2
    if "DRIFT" in statuses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
