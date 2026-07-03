"""wradlib comparison tests (RADOLAN RW) — verify our parser matches the reference.

Our radar/radolan.py and radar/georef.py are extracted from wradlib; these tests
are the golden check that the extraction stayed faithful to upstream, on a real
committed RW fixture. Skips when wradlib or the fixture is unavailable.
"""

import bz2
import io
from pathlib import Path

import numpy as np
import pytest

from radar import get_radolan_grid, read_radolan_composite

FIXTURES = Path(__file__).parent.parent / "fixtures"
RW_BZ2 = FIXTURES / "radolan_rw_sample.bin.bz2"


@pytest.mark.wradlib
def test_radolan_data_matches_wradlib():
    """Element-wise parse match between our reader and wradlib on the RW fixture."""
    wrl = pytest.importorskip("wradlib")
    if not RW_BZ2.exists():
        pytest.skip("RADOLAN fixture not found — run scripts/create_fixture.py")

    raw = RW_BZ2.read_bytes()
    data_ours, attrs_ours = read_radolan_composite(bz2.open(io.BytesIO(raw)))
    data_ref, attrs_ref = wrl.io.read_radolan_composite(bz2.open(io.BytesIO(raw)))

    data_ours = np.asarray(data_ours, dtype=float)
    data_ref = np.asarray(data_ref, dtype=float)
    assert data_ours.shape == data_ref.shape
    assert attrs_ours["producttype"] == attrs_ref["producttype"]

    # Compare finite cells (both readers mark nodata with the same sentinel/NaN).
    mask = np.isfinite(data_ours) & np.isfinite(data_ref)
    np.testing.assert_allclose(data_ours[mask], data_ref[mask], rtol=1e-6, atol=1e-6)


@pytest.mark.wradlib
def test_radolan_grid_matches_wradlib():
    """Our vendored RADOLAN WGS84 grid matches wradlib's (trig projection)."""
    wrl = pytest.importorskip("wradlib")

    ours = get_radolan_grid(wgs84=True, crs="trig")
    ref = wrl.georef.get_radolan_grid(wgs84=True, crs="trig")

    np.testing.assert_allclose(ours, ref, rtol=1e-6, atol=1e-6)
