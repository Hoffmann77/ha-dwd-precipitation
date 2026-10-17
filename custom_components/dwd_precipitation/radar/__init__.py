"""Readers for DWD radar data (ODIM_H5) and the DE1200 grid lookup.

Exports what the integration uses. The whole-grid readers
(odim.read_odim_composite, odim.read_odim_classification) are the oracle for
the test tiers and scripts/, which import them from radar.odim.
"""

from .odim import (
    read_odim_composite_cell,
    read_odim_classification_cell,
    get_rs_grid_index,
    rs_grid_contains,
    RS_GRID_SHAPE,
)

__all__ = [
    "read_odim_composite_cell",
    "read_odim_classification_cell",
    "get_rs_grid_index",
    "rs_grid_contains",
    "RS_GRID_SHAPE",
]
