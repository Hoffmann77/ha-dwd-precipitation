# 0004 — RW and SF are read in their HDF5 edition

:::note[Noch nicht übersetzt]

Diese Seite ist noch nicht ins Deutsche übersetzt; bis dahin steht hier die englische Fassung.

:::

Status: accepted (2026.10.1)

## Context

Up to 2026.10.0 RW and SF were read in DWD's legacy binary edition (.bz2, a
national 900x900 spherical grid), with a reader extracted from wradlib
(`radar/radolan.py`, `radar/georef.py`). DWD announced that the binary
edition would be switched off; the same analyses are published in an HDF5
edition (`raa01-<p>_10000-<yymmddHHMM>-dwd---bin.hdf5`), ODIM_H5 on the
DE1200 grid that RS, RV and HymecNG already use.

## Decision

Read RW and SF in the HDF5 edition, through the same `read_odim_composite_cell`
and grid lookup as the RADVOR products. The binary reader was removed with its
tests and fixtures; git history has them if the binary edition is ever needed
again.

## Consequences

The two editions are the same analysis on different grids, not a cell-for-cell
copy. Checked on live files (2026-10-12): area means over ~1100 locations agree
to 1 % (SF 0.717 vs 0.725 mm), while a location's own value differs in ~65-80 %
of wet cases (median 0.1 mm, up to a few mm in sharp gradients), and is found
in the old cell's 3x3 neighbourhood only ~60 % of the time. Users see small
value changes at the switch; nothing else changes.

Timing: RW's HDF5 file appears ~25.7 min after its window ends, like the binary
one; SF's ~29.3 min, ~2.5 min later than its binary one, hence SF's
`RELEASE_DELAY` of 31 min.
