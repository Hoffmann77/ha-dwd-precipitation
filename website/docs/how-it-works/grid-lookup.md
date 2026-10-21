---
title: Grid cell lookup
description: How your location becomes one 1 km radar grid cell, and which locations are covered.
---

DWD's radar products are grids, not point forecasts. The integration reports
the value of the one grid cell that contains your location.

## The grid

All products are on DWD's "DE1200" grid: 1100 × 1200 cells of 1 km × 1 km in
a polar stereographic projection, covering Germany and a band beyond its
borders. Where the grid reaches beyond what DWD's radars see, its cells hold
no data. Each cell holds one value per file: an amount, a
rate or a class.

So the sensors describe a square of about 1 km around your location. Two
places a few hundred metres apart usually read the same cell; a neighbour
1 km away can see a summer shower differently.

## Finding the cell

Your latitude and longitude are projected onto the grid, and the integration
takes the cell your point falls *into*, not the one whose centre happens to
be nearest. That matches how DWD defines the grid, so the value is the one
DWD's own tools show for your location.

The integration reads the grid each file describes in its header, rather
than a copy of the grid kept in the code. If DWD ever moves or resizes a
grid, the integration keeps reading the cell that holds your location. A file
on a grid it cannot interpret is refused instead of being read at the wrong
cell.

## Which locations are covered

- **At setup**, a location is accepted when it lies within a box around the
  grid (latitude 45.6° to 56.3°, longitude 1.4° to 18.8°). This box is
  larger than the grid, since no file is at hand during setup.
- **When a product is read**, a location off its grid is reported in the
  log: *The configured location is not on the grid of the … release: DWD's
  radar does not cover it.* Set the integration up again with a location
  inside Germany.
- **Near the borders**, the grid reaches further than the radars see. A cell
  without radar coverage holds "no data", and its sensors are `unknown`. The
  log then warns that there is no radar data for your location right after
  setup.

## No data for a cell

Even inside Germany, a cell can be without data for a while: when a radar is
out of service, DWD builds the composite without it, and the cells only that
radar covered are empty. The sensors are then `unknown`, and the log names
the missing radar when it can tell. See
[Availability and staleness](availability.md#no-data-for-your-location).
