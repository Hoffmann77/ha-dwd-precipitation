# Tests

Tests are split into **five tiers**, one directory per dependency group. Each tier
maps to a CI job, and jobs select tests **by directory** — so a new test file is
picked up automatically, with no CI edit required.

| Dir | Needs HA? | Needs network? | Dep group | CI job | Gates PRs? |
|-----|-----------|----------------|-----------|--------|------------|
| `parser/` | no | no | `unit-test` | `parser-tests` | ✅ |
| `integration/` | yes | no | `ha-test` | `integration-tests` | ✅ |
| `reference/` | no | no | `wradlib-comparison` | `reference-tests` | ✅ |
| `live/` | no | **yes** | `unit-test` | `live.yml` (scheduled) | ❌ notify |
| `live_wradlib/` | no | **yes** | `wradlib-comparison` | `live-wradlib.yml` (scheduled) | ❌ notify |

Guiding principle: **PR-gating tests are deterministic; anything that depends on the
outside world (DWD OpenData, newer Home Assistant) runs on a schedule and opens a
tracking issue on failure instead of blocking merges.**

## What each tier covers

- **`parser/`** — the vendored radar parsers and pure helpers, no HA/network:
  `test_odim.py` (ODIM_H5 read + DE1200 grid), `test_tar_range.py` (range reads
  of tar members), `test_rain_events.py` (the rain-event tracker),
  `test_translations.py` (en/de key parity), `test_utils.py` (release-timing math
  and the HTTP helper).
- **`integration/`** — the HA-facing layer (imports `homeassistant`):
  `test_config_flow.py`, `test_setup_entry.py` (entry → coordinators → sensor states),
  `test_product_<rs|rv|hymecng|radolan>.py` (each product's fetch and parse, helpers
  in `product_helpers.py`), `test_product_rv_rain_events.py` (RV's tracker glue),
  `test_products.py` (URLs and shared downloads), `test_coordinator_timing.py`,
  `test_sensor.py`. `conftest.py` has the `make_entry` / `make_coordinator`
  factories, which build through the real constructors.
- **`reference/`** — golden comparison of our extracted parsers and grid lookups
  against pure `wradlib` (RS on the DE1200 grid), on the committed fixtures. Skips if
  `wradlib` or the fixture is missing. The wradlib side lives in
  `tests/wradlib_ref.py` and never imports our `radar/` code.
- **`live/`** — downloads and parses the **real** DWD files for every product, walking
  back several releases (OpenData publishes with a delay). Catches URL/format/archive
  drift at the source, and reads RS by range as the integration does, so a lost
  range support or a changed tar layout fails here rather than as a silent
  fallback. Marked `@pytest.mark.live`; HA-free by design: the URLs come from the
  HA-free `radar/urls.py`, the same patterns the integration fetches.
- **`live_wradlib/`** — the reference comparison on **today's** DWD files for every
  product (RS, RV, HymecNG, RW, SF). For a fixed set of German locations it checks
  that our lookup lands on the same cell as wradlib and that the production read
  path (`read_odim_composite_cell` / `read_odim_classification`, RW/SF read in
  their HDF5 edition) returns the same value, and that every member's full
  grid decodes identically. The full-grid check is what catches a decode error on
  a dry day, when every fixed location reads 0.

  Run it by hand from the Actions tab (**Live wradlib comparison → Run workflow**)
  to check your own places against the newest files, e.g. where the radar shows
  rain right now: `locations` takes `name=lat,lon` or `lat,lon` separated by `;`.
  The job summary gets a table of every product's value per location. Locally the
  same input is the `DWD_LOCATIONS` env var. Manual runs never open the tracking
  issue.

## Running locally

```sh
# Fast, deterministic, no HA (parser + reference; reference skips without wradlib)
uv run --group unit-test pytest tests/parser
uv run --group wradlib-comparison pytest tests/reference

# HA runtime (Linux only — pytest-homeassistant-custom-component imports fcntl)
uv run --group ha-test pytest tests/integration

# Live source check (hits DWD OpenData; normally only runs on a schedule)
uv run --group unit-test pytest tests/live -m live
uv run --group wradlib-comparison pytest tests/live_wradlib -m live

# Everything that doesn't need HA or the network (live tests are deselected
# unless -m live is given; see addopts in pyproject.toml)
uv run --group unit-test pytest tests
```

## Markers

- `live` — needs network to DWD OpenData (scheduled, never on PRs).
- `wradlib` — needs `wradlib` installed (reference and live_wradlib tiers).

## Fixtures & factories

- `fixtures/` holds committed real DWD samples + expected-value JSON:
  `composite_rs_sample.hd5` / `fixture_metadata.json` (RS) and
  `radolan_rw_sample.hdf5` (one real RW file in its HDF5 edition, a plain
  download from OpenData).
- Regenerate the RS fixture (downloads fresh DWD data):
  ```sh
  uv run --group wradlib-comparison python scripts/create_fixture.py
  ```
- The real RV analysis and HymecNG file (`composite_<product>_sample.hd5`, with
  a `.json` naming the cells each pins down) come from `--product rv` /
  `--product hymecng`, which wait for a release with rain. All three tiers read
  them through `tests/factories/real.py`.
- `factories/` holds shared synthetic builders (e.g. `make_odim_h5`, `make_radvor_tar`, `RangeServer`),
  imported as `from tests.factories.odim import make_odim_h5`.

## CI workflows

- `tests.yml` — PR-gating: `parser` / `integration` / `reference` jobs (by directory).
- `live.yml` — daily; live download+parse; opens/updates an issue on failure.
- `live-wradlib.yml` — daily; our parser vs. wradlib on live files; opens/updates
  an issue on failure.
- `ha-compat.yml` — weekly; integration tier against the latest / dev
  `pytest-homeassistant-custom-component`; opens an issue on failure (dev is
  experimental / non-blocking).
- `hassfest.yaml`, `validate.yaml` — daily HA manifest + HACS structural validation.

## Adding a test

Drop the file in the tier whose dependencies it needs — it will be collected and run
by that tier's job automatically. No CI change needed.
