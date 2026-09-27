"""Inputs and the human-readable results table for the live wradlib tier.

``DWD_LOCATIONS`` lets a manual run (workflow_dispatch) check chosen
coordinates against the newest files, e.g. where the radar shows rain now. The table is printed at the end of the run and, on
GitHub, written to the job summary.
"""

from __future__ import annotations

import os
import re

# Mirrors const.PRECIP_TYPE_BY_INDEX (const.py imports HA, so it cannot be
# imported here); only used to label the table.
PRECIP_TYPES = (
    "no_precipitation", "not_classified", "drizzle", "rain", "freezing_drizzle",
    "freezing_rain", "sleet", "snow", "graupel", "hail", "large_hail",
)

_ENTRY = re.compile(
    r"^\s*(?:(?P<name>[^=;]+?)\s*=\s*)?(?P<lat>[-+]?\d+(?:\.\d+)?)\s*,\s*(?P<lon>[-+]?\d+(?:\.\d+)?)\s*$"
)


def parse_locations(spec: str) -> dict[str, tuple[float, float]]:
    """Parse ``"Home=52.52,13.40; 48.14,11.58"`` into ``{name: (lat, lon)}``.

    Entries are separated by ``;`` or newlines; the ``name=`` part is optional.
    """
    out: dict[str, tuple[float, float]] = {}
    for part in re.split(r"[;\n]", spec):
        if not part.strip():
            continue
        m = _ENTRY.match(part)
        if m is None:
            raise ValueError(f"Cannot read location {part.strip()!r}; expected 'name=lat,lon' or 'lat,lon'")
        lat, lon = float(m["lat"]), float(m["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Location {part.strip()!r} is not a valid lat,lon")
        out[(m["name"] or f"{lat},{lon}").strip()] = (lat, lon)
    return out


def custom_locations() -> dict[str, tuple[float, float]]:
    return parse_locations(os.environ.get("DWD_LOCATIONS", ""))


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------

# {place: {column: text}}, filled by the per-location tests in the order they run.
ROWS: dict[str, dict[str, str]] = {}
# {product: url of the file compared}
SOURCES: dict[str, str] = {}

COLUMNS = (
    ("cell", "DE1200 cell"),
    ("rs_000", "RS last 1h (mm)"),
    ("rs_060", "RS next 1h (mm)"),
    ("rs_120", "RS next 1-2h (mm)"),
    ("rv_000", "RV now (mm/h)"),
    ("rv_max", "RV peak next 2h (mm/h)"),
    ("hymecng", "Type"),
    ("rw", "RW last 1h (mm)"),
    ("sf", "SF last 24h (mm)"),
    ("match", "Matches wradlib"),
)


def record(place: str, **values: str) -> None:
    ROWS.setdefault(place, {}).update(values)


def mark(place: str, product: str, ok: bool) -> None:
    row = ROWS.setdefault(place, {})
    failed = set(filter(None, row.get("_failed", "").split(",")))
    passed = set(filter(None, row.get("_passed", "").split(",")))
    (passed if ok else failed).add(product)
    row["_failed"], row["_passed"] = ",".join(sorted(failed)), ",".join(sorted(passed))
    row["match"] = "yes" if not failed else "NO: " + ", ".join(sorted(failed))


def fmt(value: float | None, digits: int = 2) -> str:
    if value is None or value != value:  # None or NaN
        return "no data"
    return f"{value:.{digits}f}"


def render() -> str:
    if not ROWS:
        return ""
    lines = [
        "### DWD values per location (our parser; compared against wradlib)",
        "",
        "| Location | " + " | ".join(title for _, title in COLUMNS) + " |",
        "|---" * (len(COLUMNS) + 1) + "|",
    ]
    for place, row in ROWS.items():
        lines.append(f"| {place} | " + " | ".join(row.get(k, "-") for k, _ in COLUMNS) + " |")
    if SOURCES:
        lines += ["", "Files:", ""] + [f"- `{p}`: {url}" for p, url in sorted(SOURCES.items())]
    return "\n".join(lines) + "\n"
