"""The real DWD files in tests/fixtures and the cells each one pins down.

Made by ``scripts/create_fixture.py --product rv|hymecng``: an RV analysis
member and a HymecNG file, each with a JSON listing cells by kind (wet,
undetect, nodata) with their row/col, centre lat/lon and expected value.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parents[1] / "fixtures"


@cache
def real_member(product: str) -> tuple[bytes, dict[str, Any]]:
    """Return the fixture's bytes and its metadata (``rv`` or ``hymecng``)."""
    stem = FIXTURES / f"composite_{product}_sample"
    meta = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    return stem.with_suffix(".hd5").read_bytes(), meta


def real_cells(product: str) -> dict[str, dict[str, Any]]:
    """Return the fixture's cells by kind."""
    return {cell["kind"]: cell for cell in real_member(product)[1]["cells"]}


def real_release(product: str) -> datetime:
    """Return the release the fixture comes from (UTC)."""
    return datetime.fromisoformat(real_member(product)[1]["source_ts"])
