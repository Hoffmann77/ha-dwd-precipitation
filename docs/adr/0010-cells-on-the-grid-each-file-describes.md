# 0010 — Each product reads its cell on the grid its file describes

Status: accepted (2026.11.0)

## Context

Up to 2026.10.1 the integration carried its own copy of DWD's DE1200 grid
(`RS_WHERE` and hard-coded projection constants in `radar/odim.py`), computed
each coordinator's cell from it once, and read that row and column from every
file. Each file also describes its grid itself, in its ODIM `/where` group. Had
DWD moved or resized the grid, every install would have kept reading the old
cell, by then another place's rain, until a fixed release was out and
installed: the tests would have noticed, the users would not.

On 17 Oct 2026 the `/where` groups of the RS fixture and of live RS, RV,
HymecNG, RW and SF files, each built into a grid with nothing taken from our
constants, gave the built-in lookup's cell for 100,000 random locations each.
RW and SF spell the grid differently from the RADVOR products and HymecNG:
another parameter order in `projdef`, the corners rounded to 8 decimals
(0.3 mm), `y_0` 0.4 nm apart.

## Decision

Every reader finds the cell holding the location on the grid its file
describes. `radar/grid.py` reads `/where`: north-polar stereographic only,
tolerant of how it is spelled, refusing anything that could move a cell. The
payload must be exactly that grid, its declared size capped (`MAX_CELLS`), and
each description's grid is built once. The built-in grid, the coordinators'
`index` and the `where=` override (which nothing passed) are gone.

The config flow has no file to read a grid from, so it checks a
latitude/longitude box around DE1200 instead of the exact grid; a location in
the box but off a product's grid is reported as such when it is read.

## Alternatives

- Keep the built-in grid and compare each file's `/where` with it at runtime:
  a harmless change of spelling (RW's already differs) would take every
  install down at once.
- Keep the built-in grid, build it from one `/where` description, and compare
  live files only in the daily tests: a grid change would be noticed within a
  day, but users would read the wrong place until a release.
- Download a file in the config flow to validate the location exactly: network
  failures in setup, for a check a box does well enough.

## Consequences

- A shifted or resized grid in the same projection is followed without a
  release, and the totals and the dry streak stay on the same place.
- A file in another projection, or with a parameter that could move a cell,
  is refused: its sensors go unavailable with "please report it" rather than
  showing another place's values.
- A DWD grid change no longer fails anything users see. The daily wradlib
  tier, which checks each file's grid against wradlib's DE1200, is where it
  shows.
- A file published with wrong `/where` attributes would be read wrong for that
  release; the same tier would show it.
