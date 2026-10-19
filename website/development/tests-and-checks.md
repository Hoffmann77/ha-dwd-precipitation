---
title: Tests and checks
description: The test tiers of DWD Precipitation, the CI workflows, and how to run them locally.
---

## The test tiers

Tests are split into five tiers, one directory per dependency group. Each
tier maps to a CI job, and jobs select tests by directory, so a new test file
is picked up without any CI change.

| Directory | Needs Home Assistant | Needs network | Dependency group | Gates PRs |
|-----------|---------------------|---------------|------------------|-----------|
| `tests/parser/` | no | no | `unit-test` | yes |
| `tests/integration/` | yes | no | `ha-test` | yes |
| `tests/reference/` | no | no | `wradlib-comparison` | yes |
| `tests/live/` | no | yes | `unit-test` | no, scheduled |
| `tests/live_wradlib/` | no | yes | `wradlib-comparison` | no, scheduled |

The principle: tests that gate pull requests are deterministic. Anything that
depends on the outside world (DWD Open Data, a newer Home Assistant) runs on
a schedule and opens a tracking issue when it fails, rather than blocking
merges.

- **parser**: the Home-Assistant-free code, plus repository-wide checks: the
  English and German translations define the same keys, the Upgrading page
  names every renamed entity's old id, and every page of this site exists in
  both languages.
- **integration**: the Home Assistant layer, on a real `hass` instance.
- **reference**: the parsers and grid lookup against
  [wradlib](https://github.com/wradlib/wradlib), on committed real DWD files.
- **live**: downloads and parses today's real files, including the range
  reads, and checks that RS still equals the sum of RV's steps.
- **live_wradlib**: the wradlib comparison on today's files for every
  product. This is where a change of DWD's grid would show, since the
  integration itself follows it.

## Running them locally

```sh
# Fast, deterministic, no Home Assistant
uv run --group unit-test pytest tests/parser
uv run --group wradlib-comparison pytest tests/reference

# Home Assistant runtime (Linux only)
uv run --group ha-test pytest tests/integration

# Live checks against DWD Open Data
uv run --group unit-test pytest tests/live -m live
uv run --group wradlib-comparison pytest tests/live_wradlib -m live
```

`tests/README.md` describes the fixtures and factories, and how to
regenerate the real-file fixtures.

## Lint and type checks

- **ruff** (F rules only) on the repository:
  `uv run --only-group lint ruff check .`
- **pyright** (basic mode) on the component, against Home Assistant's own
  types: `uv sync --only-group typecheck && uv run --no-sync pyright`. Keep it
  at 0 errors: fix a finding, or ignore it on its line with the reason.

## CI workflows

| Workflow | When | What |
|----------|------|------|
| `tests.yml` | PRs, pushes to main | parser, integration and reference tiers, ruff, pyright |
| `docs-build.yml` | PRs touching the docs | builds this site in both languages; fails on broken links |
| `docs-deploy.yml` | a release is published | publishes this site to GitHub Pages |
| `live.yml` | daily | live download and parse; opens an issue on failure |
| `live-wradlib.yml` | daily, or by hand | wradlib comparison on live files; opens an issue on failure |
| `ha-compat.yml` | weekly | the integration tier against the latest and dev Home Assistant test harness |
| `hassfest.yaml`, `validate.yaml` | daily | Home Assistant manifest and HACS validation |
| `release-delay.yml` | scheduled | checks each product's `RELEASE_DELAY` against DWD's actual publication |
| `release-drafter.yml` | pushes to main, PRs | drafts the next release notes |

### Live wradlib comparison for your own places

`live-wradlib.yml` can be run by hand from the Actions tab (**Live wradlib
comparison > Run workflow**) to check your own places against the newest
files, for example where the radar shows rain right now. Its `locations`
input takes `name=lat,lon` or `lat,lon`, separated by `;`. The job summary
gets a table of every product's value per location. Locally the same input
is the `DWD_LOCATIONS` environment variable.

### Release delay check

`scripts/check_release_delay.py` averages the observed delay of recent files
(their `Last-Modified` header minus the nominal time in the name) and flags a
product whose mean exceeds its configured `RELEASE_DELAY`. The workflow opens
or updates a tracking issue only when a product is flagged on two
consecutive runs, so one-off noise does not page anyone.
