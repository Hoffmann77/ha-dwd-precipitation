# 0008 — The grid lookup floors from the outer corner

:::note[Noch nicht übersetzt]

Diese Seite ist noch nicht ins Deutsche übersetzt; bis dahin steht hier die englische Fassung.

:::

Status: accepted (2026.10.0)

## Context

ODIM's `LL_*`/`UL_*`/`UR_*`/`LR_*` attributes are the outer corners of the
edge pixels, not pixel centres. Both lookups the integration had (the DE1200
one for RADVOR, the national one for the RADOLAN binary edition) treated them
as centres, which shifts the lookup by half a cell and picks a neighbouring
cell for ~3 locations in 4. Both were wrong that way until 2026.10.0.

## Decision

Project the location, then floor its offset from the grid's outer lower-left
corner. Never round, and never take the nearest grid coordinate.

The reference tier checks the result against wradlib's own grid (`mode="edge"`)
rather than a reimplementation of our arithmetic, which could repeat the same
mistake, and pins wradlib's grid to the fixture file's corner attributes.

## Consequences

Since RW and SF moved to the HDF5 edition
([0004](0004-radolan-hdf5-edition.md)) there is only the DE1200 lookup.
