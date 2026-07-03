# Tests

Tests are split into **four tiers**, one directory per dependency group. Each tier
maps to a CI job, and jobs select tests **by directory** — so a new test file is
picked up automatically, with no CI edit required.

| Dir | Needs HA? | Needs network? | Dep group | CI job | Gates PRs? |
|-----|-----------|----------------|-----------|--------|------------|
| `parser/` | no | no | `unit-test` | `parser-tests` | ✅ |
| `integration/` | yes | no | `ha-test` | `integration-tests` | ✅ |
| `reference/` | no | no | `wradlib-comparison` | `reference-tests` | ✅ |
| `live/` | no | **yes** | `unit-test` | `live.yml` (scheduled) | ❌ notify |

Guiding principle: **PR-gating tests are deterministic; anything that depends on the
outside world (DWD OpenData, newer Home Assistant) runs on a schedule and opens a
tracking issue on failure instead of blocking merges.**

## What each tier covers

- **`parser/`** — the vendored radar parsers and pure helpers, no HA/network:
  `test_odim.py` (ODIM_H5 read + RS grid), `test_radolan.py` (RADOLAN binary, against a
  committed fixture), `test_georef.py` (RADOLAN grid transform), `test_utils.py`
  (release-timing math).
- **`integration/`** — the HA-facing layer (imports `homeassistant`):
  `test_config_flow.py`, `test_setup_entry.py` (entry → coordinators → sensor states),
  `test_products.py` (fetch/parse metadata derivation), `test_coordinator_timing.py`,
  `test_sensor.py`.
- **`reference/`** — golden comparison of our extracted parsers against
  `wradlib` + `pyproj` (RS and RADOLAN). Individual tests `skip` if `wradlib` or the
  fixture is missing.
- **`live/`** — downloads and parses the **real** DWD files for every product, walking
  back several releases (OpenData publishes with a delay). Catches URL/format/archive
  drift at the source. Marked `@pytest.mark.live`; HA-free by design (base URLs are
  hardcoded because `const.py` imports HA).

## Running locally

```sh
# Fast, deterministic, no HA (parser + reference; reference skips without wradlib)
uv run --group unit-test pytest tests/parser
uv run --group wradlib-comparison pytest tests/reference

# HA runtime (Linux only — pytest-homeassistant-custom-component imports fcntl)
uv run --group ha-test pytest tests/integration

# Live source check (hits DWD OpenData; normally only runs on a schedule)
uv run --group unit-test pytest tests/live -m live

# Everything that doesn't need HA or the network
uv run --group unit-test pytest tests -m "not live"
```

## Markers

- `live` — needs network to DWD OpenData (scheduled, never on PRs).
- `wradlib` — needs `wradlib` installed (reference tier).

## Fixtures & factories

- `fixtures/` holds committed real DWD samples + expected-value JSON:
  `composite_rs_sample.hd5` / `fixture_metadata.json` (RS) and
  `radolan_{rw,sf}_sample.bin.bz2` / `radolan_metadata.json` (RADOLAN).
- Regenerate them (downloads fresh DWD data; **overwrites the RS fixture too**):
  ```sh
  uv run --group wradlib-comparison python scripts/create_fixture.py
  ```
- `factories/` holds shared synthetic builders (e.g. `make_odim_h5`, `make_rs_tar`),
  imported as `from tests.factories.odim import make_odim_h5`.

## CI workflows

- `tests.yml` — PR-gating: `parser` / `integration` / `reference` jobs (by directory).
- `live.yml` — daily; live download+parse; opens/updates an issue on failure.
- `ha-compat.yml` — weekly; integration tier against pinned / latest / dev
  `pytest-homeassistant-custom-component`; opens an issue on failure (dev is
  experimental / non-blocking).
- `hassfest.yaml`, `validate.yaml` — daily HA manifest + HACS structural validation.

## Adding a test

Drop the file in the tier whose dependencies it needs — it will be collected and run
by that tier's job automatically. No CI change needed.
