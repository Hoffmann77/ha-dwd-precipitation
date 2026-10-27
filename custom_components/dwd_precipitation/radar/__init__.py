"""Readers for DWD radar data (ODIM_H5), each on the grid its own file describes.

Exports what the integration uses. The whole-grid readers and read_odim_grid
(radar.odim) are for the test tiers and scripts/, which import them from there.

"""

from .grid import OutsideGrid, UnsupportedGrid
from .nearby import nearest_class
from .odim import (
    read_odim_classification_at,
    read_odim_classification_near,
    read_odim_composite_at,
)

__all__ = [
    "OutsideGrid",
    "UnsupportedGrid",
    "nearest_class",
    "read_odim_classification_at",
    "read_odim_classification_near",
    "read_odim_composite_at",
]
