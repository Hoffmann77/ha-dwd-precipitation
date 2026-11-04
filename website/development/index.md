---
title: Development
description: How the DWD Precipitation project is organised, and where to start as a contributor.
---

DWD Precipitation is a Home Assistant custom integration written in Python.
These pages are for people who want to understand or change it. If you just
want to use it, the [user docs](/) are the place to start.

## The repository

| Path | What it holds |
|------|---------------|
| `custom_components/dwd_precipitation/` | The integration itself |
| `custom_components/dwd_precipitation/radar/` | The Home-Assistant-free core: file readers and pure domain logic |
| `tests/` | Five test tiers, see [Tests and checks](tests-and-checks.md) |
| `scripts/` | Tools to create fixtures and check DWD's publication delays |
| `docs/adr/` | The [architecture decision records](/development/adr) |
| `website/` | This documentation site, see [Working on these docs](documentation.md) |
| `CLAUDE.md` | The codebase guide: the rules the code follows, kept next to it |

## Where to read on

- [Architecture](architecture.md): the modules, how data flows from DWD to
  an entity, and how failures are handled.
- [Adding a DWD product](adding-a-product.md): the checklist.
- [Tests and checks](tests-and-checks.md): what runs where, and how to run it
  locally.
- [Architecture decisions](/development/adr): why things are the way they
  are, and what they were before.

## Getting set up

The project uses [uv](https://docs.astral.sh/uv/) for its Python
environments. Each test tier has its own dependency group, so a fast tier
does not need Home Assistant installed:

```sh
git clone https://github.com/Hoffmann77/ha-dwd-precipitation.git
cd ha-dwd-precipitation
uv run --group unit-test pytest tests/parser
```

To try a change in a real Home Assistant, copy (or symlink)
`custom_components/dwd_precipitation` into the `custom_components` folder of
a development instance and restart it.

## Contributing

- Bugs and ideas go to
  [GitHub issues](https://github.com/Hoffmann77/ha-dwd-precipitation/issues).
- Pull requests are welcome. Keep a change focused, add tests in the tier
  that fits, and update the docs it affects, in English and German.
- A decision that changes how the integration behaves, or overturns an
  earlier one, gets an ADR.
- Only dependencies with binary wheels that install cleanly in Home
  Assistant are acceptable. Today that is `numpy` and `h5py`; heavy packages
  such as wradlib, pyproj or GDAL are not.
