"""Readers for DWD radar data (ODIM_H5) and the DE1200 grid lookup.

Exports what the integration uses. read_odim_classification (whole grid) is
needed for the optional neighbourhood scan; odim.read_odim_composite is the
oracle for the test tiers and scripts/, which import it from radar.odim.
"""

from .odim import (
    read_odim_composite_cell,
    read_odim_composite_window,
    read_odim_classification,
    read_odim_classification_cell,
    get_rs_grid_index,
    rs_grid_contains,
    RS_GRID_SHAPE,
)

__all__ = [
    "read_odim_composite_cell",
    "read_odim_composite_window",
    "read_odim_classification",
    "read_odim_classification_cell",
    "get_rs_grid_index",
    "rs_grid_contains",
    "RS_GRID_SHAPE",
]
