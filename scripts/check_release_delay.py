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
nominal timestamps ``k*I + O`` — the timestamp encoded in each filename. For
each of the most recent files we read its ``Last-Modified`` response header,
which is the moment DWD actually published the file (RFC 7231 mandates GMT, so
there is no timezone ambiguity). The observed delay of one file is

    Last-Modified − nominal_timestamp

and we average that over the last ``--samples`` published files — DWD keeps a
rolling window of them, so this is a stable central estimate rather than a
single noisy probe. No polling or waiting: every sample is an exact, already
published fact.

A product is flagged when ``|configured − mean(observed)| > grace``.

Exit status: ``0`` all products within tolerance, ``1`` at least one drifted,
``2`` a product could not be measured (too few files / network error).

Usage::

    uv run --group unit-test python scripts/check_release_delay.py
    uv run --group unit-test python scripts/check_release_delay.py --products rs
    uv run --group unit-test python scripts/check_release_delay.py --samples 36
"""

from __future__ import annotations

import argparse
import ast
import os
import statistics
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

# Stop scanning back once this many consecutive nominal slots are missing —
# either we are above the frontier (newest not published yet) with a wildly
# wrong delay, or we fell off the folder's retention window.
_MISS_CAP = 8


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


def http_last_modified(url: str, timeout: float = 60.0, attempts: int = 3) -> datetime | None:
    """Return the file's ``Last-Modified`` time (UTC), or None if it is absent.

    Uses HEAD (no body) and falls back to a streamed GET if HEAD is rejected.
    Raises on network errors after retries so a flaky run is not read as "no
    drift".
    """
    import requests  # imported lazily so the module loads without the dep
    from email.utils import parsedate_to_datetime

    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 405:  # some servers disallow HEAD
                resp = requests.get(url, stream=True, timeout=timeout)
                resp.close()
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.headers.get("Last-Modified")
            if not raw:
                return None
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
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
    deltas: list[timedelta] = field(default_factory=list)
    error: str | None = None

    @property
    def observed(self) -> timedelta | None:
        """Mean observed delay across the sampled files."""
        if not self.deltas:
            return None
        return sum(self.deltas, timedelta()) / len(self.deltas)

    @property
    def spread(self) -> tuple[timedelta, timedelta] | None:
        if not self.deltas:
            return None
        return (min(self.deltas), max(self.deltas))

    @property
    def stdev(self) -> timedelta | None:
        if len(self.deltas) < 2:
            return timedelta()
        return timedelta(seconds=statistics.stdev(d.total_seconds() for d in self.deltas))

    @property
    def deviation(self) -> timedelta | None:
        if self.observed is None:
            return None
        return abs(self.configured - self.observed)

    def status(self, grace: timedelta) -> str:
        if self.error is not None or self.observed is None:
            return "ERROR"
        return "OK" if self.deviation <= grace else "DRIFT"


def measure(
    spec: ProductSpec,
    configured: dict[str, timedelta],
    now: datetime,
    *,
    last_modified: Callable[[str], datetime | None] = http_last_modified,
    samples: int = 24,
    min_samples: int = 3,
) -> Measurement:
    """Average the observed availability delay over recent published files.

    Walks the release schedule backward from ``now``, reading each file's
    publication time, until ``samples`` files have been measured or the folder's
    recent window is exhausted.
    """
    interval = configured["RELEASE_INTERVAL"]
    offset = configured["RELEASE_OFFSET"]
    delay = configured["RELEASE_DELAY"]
    m = Measurement(spec.key, spec.class_name, delay, interval)

    try:
        ts = previous_release(now, interval, offset)
        max_scan = samples * 3 + _MISS_CAP
        consecutive_misses = 0
        scanned = 0

        while len(m.deltas) < samples and scanned < max_scan:
            scanned += 1
            published = last_modified(spec.url_for(ts))
            if published is None:
                consecutive_misses += 1
                if consecutive_misses > _MISS_CAP:
                    break
            else:
                consecutive_misses = 0
                m.deltas.append(published - ts)
            ts -= interval

        if len(m.deltas) < min_samples:
            m.error = (
                f"only {len(m.deltas)} published file(s) found in the last "
                f"{scanned} slots (need {min_samples})"
            )
    except Exception as err:  # network / logic — reported, never crashes the run
        m.error = str(err)

    return m


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
    header = f"{'product':<8}{'status':<8}{'configured':>12}{'observed':>12}{'deviation':>12}{'grace':>10}"
    lines = [header, "-" * len(header)]
    for m in measurements:
        lines.append(
            f"{m.key:<8}{m.status(grace):<8}"
            f"{_fmt(m.configured):>12}{_fmt(m.observed):>12}"
            f"{_fmt(m.deviation):>12}{_fmt(grace):>10}"
        )
        if m.error:
            lines.append(f"         └ error: {m.error}")
        elif m.spread:
            lines.append(
                f"         └ {len(m.deltas)} files | "
                f"min {_fmt(m.spread[0])}, max {_fmt(m.spread[1])}, "
                f"σ {_fmt(m.stdev)}"
            )
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
        help="allowed deviation of the mean observed delay, in minutes (default: 5)",
    )
    parser.add_argument(
        "--samples", type=int, default=24,
        help="number of recent files to average per product (default: 24)",
    )
    parser.add_argument(
        "--min-samples", type=int, default=3,
        help="minimum files required to report a measurement (default: 3)",
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
            measure(spec, configured, now, samples=args.samples, min_samples=args.min_samples)
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
