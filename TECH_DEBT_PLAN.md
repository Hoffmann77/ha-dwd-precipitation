# Joint remediation plan — tech-debt audit + /simplify

Scope: `main...HEAD` on `claude/tech-debt-identification-21b444` (55 commits,
2026.10.0 and everything after). Two analyses merged:

- **TD** — tech-debt audit (bugs, scored debt items 1-20)
- **S** — /simplify review (reuse, simplification, efficiency, altitude)

Duplicates are merged into one task; the source tags show where each came
from. Baseline today: parser 129 / integration 193 / reference 10 tests pass,
~87 % coverage, lock up to date.

## Agreed decisions (Q&A, 2026-10-13)

**Delivery**
- One branch (this worktree), **one commit per task**, tests green at
  every commit. "PR n" below = plan step n, not a separate pull request.
- **Scope: steps 1-4, then reassess** steps 5-10 on the new base.
- Bug fixes ship with the next release (no separate patch).
- Verification per commit: parser tier natively, integration + reference
  tiers in a python3.14 Docker container (integration cannot run on
  Windows: fcntl).

**Behaviour**
- Dry streak follows `data_is_reportable` like every entity (goes
  unavailable when stale) — release-note it.
- Rain-events fill runs as an entry-scoped **background task**; setup waits
  for one fetch only. *Revised during step 1:* the fill must stay *before*
  the tracker update (update-then-fill swaps event ids and loses
  `forecast_at_onset` after a downtime with rain — reproduced), so the
  background round does fill + update + publish, and the sensor **holds its
  previous view** meanwhile (unknown right after a restart).
- Rain-events Store validation/migration stays in **step 6** (not pulled forward).
- HTTP timeout is **stall-based**: `sock_connect=15 s`, `sock_read=30 s`, no total cap.
- Overlapping refreshes **wait on a lock**; the second sees the release
  already fetched and returns the cache. *Found during step 1:* HA's
  `async_refresh` already holds such a lock and every trigger uses it, so
  no lock of our own; a test pins the behaviour and the call sites.
- Decode failures: distinct message ("could not be decoded; likely a change
  on DWD's side or a bug in the integration - please report it"), same
  once-per-run flow, traceback once at DEBUG.
- Range-read fallback: **WARNING once per run** when fallbacks start, INFO
  when range reads work again.
- `window_start` / `window_end` on intensity-now and peak-hour sensors →
  unrecorded.

**Code / tooling**
- `ReleaseGrid` in a **new HA-free module**.
- ruff starts with **`F` only**.
- GitHub Actions pinning **left as is** (only nothing else changes there).
- `ha-compat.yml`: **drop the `pinned` leg**, keep `latest` + `dev`; no
  minimum HA version declared in `hacs.json`.
- `read_odim_composite` stays in `radar/odim.py`, removed from
  `radar/__init__` exports, docstring says it is a test/script oracle.
- Options form de-duplicated with **small builders only** (keep
  `default=options.get(...)` semantics).

## Guiding rules for every PR

- **Behaviour-neutral unless the task says otherwise.** Refactor PRs must not
  move a state, an entity id, a unique id or a schedule. Bug-fix PRs say which
  behaviour changes and add a test for it.
- **Invariants from CLAUDE.md stay pinned:** entity `key`s / unique ids; the
  `fetch_jitter_for` derivation (pinned test); `OVERDUE_GRACE` not a multiple
  of `RELEASE_INTERVAL`; timing constants readable by
  `scripts/check_release_delay.py` via `ast`; en/de translation key parity;
  existing restore payloads and the rain-events Store (v1) still load.
- **Each PR updates CLAUDE.md / README for what it touches** (no separate
  "docs later" for changed mechanisms).
- PR order follows dependencies: guardrails first, leaf cleanups next, then
  the core API that the larger refactors stand on.

---

## PR 1 — Bug fixes (behaviour changes, each with a test)

| Task | Where | Source |
|---|---|---|
| Threshold change must take effect on the same release: check `state.wet_milli == milli` in the early return | `rain_events.py:525` | TD bug 1 |
| `at_stake` must ignore known-nodata steps — today a coverage-edge location writes the Store every 5 min forever | `rain_events.py:745-749` | S-efficiency 2 |
| Fill warning: catch `TimeoutError` (own budget → debug) and validation errors separately; only real fetch errors say "DWD did not serve it" | `products.py:546-561` | TD bug 3 |
| Run the rain-events fill + tracker update as an entry-scoped background task that publishes the view when done (previous view held meanwhile), so setup never waits up to 30 s | `products.py:473-500`, `__init__.py:72` | S-efficiency 3 |
| Stall-based `ClientTimeout(sock_connect=15, sock_read=30)` in `async_get`; test that overlapping refreshes fetch once (HA's refresh lock already serializes them) | `utils.py:156`, `coordinator.py` | TD bug 5 |
| Dry streak: availability from `data_is_reportable` (derive from `DwdCoordinatorEntity`, keep unique id) | `sensor.py:749-781` | TD 4, S-altitude |
| Invalid stored `dry_streak_source` → fall back to default with a warning instead of `KeyError` killing the platform | `sensor.py:433` | TD (sensors) 11 |
| `create_fixture.py`: restore `MIN_MM` | `scripts/create_fixture.py:128,212` | TD bug 2 |
| Delete dead `radar/util.py` + `radar/LICENSE.txt`; rewrite README license paragraph | `README.md:288-292` | TD bug 6, TD 20 |

## PR 2 — Guardrails (CI, tooling, dependencies)

Do this before the refactors so they land under lint and on-push tests.

- ruff job in `tests.yml`, rule set **`F` only** (fixes the F821 in
  `create_fixture.py`, unused imports `products.py:12`, `radar/odim.py:3`;
  `__all__` in `radar/__init__.py`). Broader rules / pyright later. *(TD 2)*
- `tests.yml`: `push: [main]`, `workflow_dispatch`, `concurrency`,
  `timeout-minutes`, `permissions: contents: read`; `uv sync --locked`
  everywhere. Action pinning unchanged. *(TD 2, TD-tests 4/5)*
- pytest: `addopts = "-m 'not live' --strict-markers"`; drop `asyncio_mode`
  warning in non-HA groups; reference job fails if 0 tests ran. *(TD-tests 17)*
- `ha-compat.yml`: remove the `pinned` leg (keep `latest`, `dev`).
- Dependencies: numpy in unit-test group pinned to HA's; raise `h5py` floor
  to the tested version; Renovate custom manager for manifest requirements;
  manifest URLs → `ha-dwd-precipitation`. *(TD 5)*

## PR 3 — Leaf cleanups (mechanical, behaviour-neutral)

Small, independent; can be split further. All S-reuse / S-simplification
unless marked.

**Dead / redundant code**
- Remove `_utc`, `DWD_RADVOR_URL`, `data_is_stale`, `get_previous_multiple(include=)`,
  `mydatetime` (plain epoch floor), single-use `_read_tar_cells`; fix stale
  RW10 docstring (":50 run") and `track_time_change_args` docstring. *(TD 20)*
- `event["unseen"]` (written, never read). `HOUR_STEPS`/`STEPS_PER_HOUR`/`WINDOW_STEPS` → one name.
- `nowcast.rolling_hour_sums(leads=)` / `peak_rolling_hour(leads)` params used only by one test → drop.
- `products.py:712` re-rounds an already rounded value.
- `sensor.py` totals: `_total`/`_last_release` always set together → drop impossible `None` guards.

**One helper instead of N copies**
- `serialize.py` (HA-free): `iso()` / `parse_utc()` replacing `dry_streak.from_dict`,
  `precipitation_total._parse_utc`, `rain_events._iso/_parse` (forces UTC — fixes
  naive datetimes), `products._iso`. *(TD 11)*
- `products._tar_members` → public `tar_range.members_from_archive`; on fallback run it in the executor. *(+ S-efficiency 6)*
- `_odim_window` in HymecNG too; `_odim_metadata(what, lead)` for the three
  `ProductMetadata` builders; `_prefix(ts)` per RADVOR class (7 copies);
  `_mm(x)` rounding helper; `read_odim_composite_cell` returns `float | None`
  (removes 3 NaN spellings + `value != value`).
- `_get_latest_release(now)` → `_release_at_or_before(now - release_delay)`.
- `_peak_hour_payload(base: ProductMetadata | None)` instead of two guarded args.
- `rain_events_store(hass, entry_id)` factory (3 `Store(...)` copies);
  `unique_id_for(entry_id, key)` in `entity.py` (used by registry removal).
- `rain_events`: `_peak` with a window predicate replaces `_total_peak_1h`;
  `final_unknown` derived; `_onset_view` / `candidate` dict merges.
- `tar_range`: `_Remote.read` returns bytes only; drop `whole_fetch`;
  `os.path.commonprefix`; name the `_locate` factors.
- `read_odim_classification` reuses `_open_composite`, reads one cell with the
  bounds check. *(TD 19, S-efficiency 11)*

**Schema boilerplate**
- `sensor.py`: shared `_MM` / `_MMH` description kwargs (~40 lines).
- `config_flow.py`: `_number(unit)` / `_select(...)` builders only;
  `default=options.get(...)` semantics unchanged.
- `read_odim_composite`: drop from `radar/__init__` exports, docstring marks
  it as the test/script oracle.

**Recorder**
- `window_start` / `window_end` on intensity-now and peak sensors →
  `_unrecorded_attributes` (~288 attribute rows/entity/day). *(S-efficiency 14; changes history only)*

**Step 3 outcome (done, 14 commits `1126d33`..`5e295bd`).** Deviations:
- *Moved to step 4:* `mydatetime`, `get_previous_multiple(include=)` and
  `_get_latest_release` → `_release_at_or_before(...)`: all release-grid
  arithmetic that `ReleaseGrid` replaces anyway.
- *Kept:* `read_odim_composite_cell` still returns NaN (it mirrors wradlib and
  the grid reader, which the reference tiers compare against); NaN → None
  happens once, in `products._nan_to_none`. The dry streak's own NaN guard
  stays: tests feed it NaN on purpose.
- *Skipped:* the `_onset_view` / `candidate` dict merges. Their explicit field
  lists are the published schema-1 contract; a merge would let stored keys
  leak into the view.
- *Placed differently:* `iso()` / `parse_utc()` live in `utils.py` (HA-free),
  not a new `serialize.py`; `rain_events.py` keeps its copies until step 6.
- *Found on the way:* a total restored without a `total` backfilled its stale
  pending releases into a total that had just restarted at 0 (fixed with the
  invariant, `2920f41`). On a range-read fallback the archive is now unpacked
  in the executor (`5092370`).
- *Verified beyond the suites:* rain_events old vs new on 1500 random
  scenarios (identical; the check flags a planted off-by-one), every sensor
  description and the options form compared field by field before and after.

## PR 4 — Coordinator core API

- *From step 3:* drop `mydatetime` and `get_previous_multiple(include=)`;
  `_get_latest_release(now)` becomes `at_or_before(now - release_delay)`.

The base the next three PRs stand on. *(TD 1, 3, 6, 10, 18; S-altitude 2, 6, 9, 11; S-efficiency 9, 10; S-simplification 1, 13)*

- **`ReleaseGrid`** value object (interval, offset, delay, tz) in an HA-free
  module: `latest(now)`, `next_after`, `at_or_before`, `walk(a, b)`,
  `back(n)`. Removes the four `USE_LOCAL_TIME` ternaries; the release-delay
  script's `previous_release` copy imports it. Class constants stay as they
  are so the `ast` reader is untouched.
- **Public `async_fetch_release(ts) -> CoordinatorData`**, no side effects —
  replaces `sensor.py:718` calling `_fetch_and_parse` and RV's
  `_async_fetch_analysis` path.
- Base-class defaults: `index` = DE1200 lookup (not abstract), default
  `_fetch_and_parse` = `_get_url` → executor `_parse(content, ts)`;
  `RadvorTarProduct` base for RS/RV. Update CLAUDE.md "Adding a new product"
  (incl. the release-delay script step).
- `precipitation_total` takes a grid, not an `Any` coordinator: bounded
  walk (`at_or_before(current - limit)`), one cutoff instead of
  `[-limit:]` + `split_fetchable`, INFO log when releases are dropped.
- Grid move (old :50 `last_release`) normalised **once at restore**, then
  `first_uncounted_release` and its branch go away.
- Backfill writes state once per round, not once per release.
- Error reporting: non-network exceptions say "could not decode, please
  report" and log the traceback at debug on the first failure of a run. *(TD 1)*
- Small `FailureLatch` (`fail(...)` / `ok()`); used for range-read fallback
  (warn once per run — TD 6), tar-member-missing warning, backfill, and the
  tracker in PR 6.

**Step 4 outcome (done, 6 commits `162f4b7`..`9d4e25c`).**
- `ReleaseGrid` (`release_grid.py`, HA-free) replaces `mydatetime` /
  `get_previous_multiple` and the coordinator's three grid methods; the
  release-delay script imports it. Checked against the old arithmetic on 345k
  instants (every product, UTC and Berlin, both 2026 changeovers): identical.
- Totals walk the grid with one cutoff (`grid.back(current, limit)`); a gap
  older than the window is logged at INFO; the HH:50 grid move is mapped once
  at restore (`counted_on_grid`). Checked against the old walk on 8000 random
  cases: identical. A year's gap now walks <100 steps instead of 8760.
- `_fetch_and_parse` is side-effect free; RV's tracker runs in the new
  `_async_on_new_release` hook; `async_fetch_release` serves the backfill.
- `index` defaults to DE1200; `WholeFileProduct` / `RadvorProduct` bases;
  `_parse(content, ts)` everywhere; CLAUDE.md's add-a-product steps updated.
- Decode failures: own message ("please report it"), traceback at DEBUG once.
- `FailureLatch`: range-read fallback (WARNING once / INFO on recovery) and
  RV's two fill/tracker flags.
- *Not done:* the latch for the per-release "tar member not found" warning
  (raised inside the executor decode; needs the missing names passed back)
  and for the backfill (it stays at DEBUG: the coordinator already reports a
  DWD outage). `RadvorRV._async_fetch_analysis` stays: a one-member range
  read, not a full release fetch.

## PR 5 — Options & entry composition

*(TD 7; S-altitude 4, 7, 8; S-reuse 7, 8; S-simplification 5)*

- Frozen **`DwdOptions.from_entry(entry)`** with one `DEFAULT_OPTIONS` table;
  config flow uses it for defaults. Built once in `async_setup_entry`, passed
  to coordinators and platforms (options reload the entry, so a snapshot is safe).
  RV `_parse` gets its option values as arguments (pure parser).
- Entity descriptions become a pure function of `DwdOptions` and declare
  `product_key` (+ features such as `rolling_series`, `rain_events`). Setup
  builds only referenced coordinators. Removes `RadolanRW10.is_needed`, the
  duplicated `rw → rw_10min` mapping, scattered `rain_events_enabled()` and
  `full_rolling_series` reads.
- Generic registry sweep removes entities whose unique id is no longer
  produced (replaces the rain-events-specific removal).
- Dry streak gets its correction sources (`rw`/`sf`) injected instead of
  reaching into `runtime_data`.
- Binary sensor uses the shared description mechanism (`attrs_fn` /
  `metadata_attrs_fn` moved into `DwdCoordinatorEntity`). Per D5,
  `forecast_5min` stays always on there, as an explicit exception.

**Step 5 outcome (done, 3 commits `88a5274`..`2c62631`).**
- `options.py`: `DEFAULT_OPTIONS` (every option's default, used by the form)
  and the frozen `DwdOptions` snapshot; coordinators read `self.options`,
  platforms `entry.runtime_data.options`. No `entry.options.get()` left
  outside it. The dry-streak source resolution lives there.
- Dry streak gets its RW/SF correction sources passed in; the restore +
  correction path now has an end-to-end test.
- Sensors and the binary sensor share one description mechanism
  (`DwdEntityDescriptionMixin` + rendering in `DwdCoordinatorEntity`);
  `forecast_5min` stays always on (D5).
- *Not done, deliberately:* descriptions declaring their products so setup
  builds only those (one optional product, `rw_10min`, already resolved
  through `DwdOptions`; not worth a cross-module mechanism), and a generic
  registry sweep (it would permanently delete users' entities, with their
  customisations, if setup ever skipped one; the explicit rain-events
  removal stays). RV's `_parse` reads the frozen snapshot rather than taking
  options as arguments.

## PR 6 — Rain events as a tracker

*(TD 9, 15, bug 4; S-altitude 3, 12; S-efficiency 4, 5)*

- `RainEventsTracker` owns Store (create/load/save/remove, with a
  `migrate_func`-capable Store subclass), fill, save policy and latch; hooked
  via a base-class `_async_on_new_release(release, data)` after a successful
  update — no longer a side effect of `_fetch_and_parse`. Removes
  `isinstance(rv, RadvorRV)` in unload, `data["rain_events"]` in the RV
  payload, and the duplicated store removal.
- Typed `Event` dataclass + `TypedDict` for the published schema-1 view;
  restored records validated, any failure → discard and start over.
- Stop persisting derived `view`s (state and per-event); recompute on load.
  Loading a v1 store that still has them must keep working (ignore the keys),
  so no version bump is needed.
- Split `update()` into prune / match / classify / publish; prefix sums for
  window peaks (O(n)); optionally run it in the executor.
- Move `rain_events.py` into `radar/` (HA-free, parser tier unchanged) so it
  imports `STEP`, `STEPS_PER_HOUR`, `MM_DECIMALS` from `nowcast` instead of copying.
  *Carried over from step 3:* it still has its own `_iso`/`_parse` (the
  latter not forcing UTC), because it cannot import a sibling module yet;
  move `utils.iso`/`utils.parse_utc` into `radar/` alongside it and use them.

**Step 6 outcome (done, 4 commits `f6a99d5`..`d9ab098`).**
- `rain_events.py` -> `radar/rain_events.py` (D4 decided: move); constants
  from `nowcast`, `iso`/`parse_utc` -> `radar/isotime.py`.
- Restored state validated field by field; any load or check failure
  discards the store once (bug 4 closed). *Deviation:* the derived views stay
  persisted - an `unseen` event is republished from its last view, and the
  stored view answers the same release after a restart (processing it twice
  is not harmless). The shortcut checks the view's schema.
- `RainEventsTracker` (`rain_events_tracker.py`) owns store, fill, save
  policy, latches; RV only hands it releases; it saves itself on unload.
- `update()` split into named steps; schema-1 declared as TypedDicts with a
  test that the published view matches. Identical views on 1000 random
  scenarios vs. before step 6.
- *Not done:* event records as a dataclass (validation covers the contract),
  prefix sums / executor (measured 1-5 ms per release).

## PR 7 — One payload shape

*(TD 14; S-altitude 5)*

- `CoordinatorData` → `Mapping[str, Reading(value, meta)]` for every product;
  scalar products use one key; RS keys like `"last_60"`, `"next_60"`, …
- Descriptions name a `sub_key`; dry streak and totals declare
  `(product_key, sub_key)`. Removes RS indices `[0..4]`,
  `PRODUCT_KEY == "rs"`, `scalar_reading`, the scalar-only `countable`
  special case, and the "data and metadata happen to have the same shape" coupling.
- Fix the type gaps (HymecNG `str`, `None` in metadata lists) along the way.

**Step 7 outcome (done, 1 commit).**
- Every product returns `Payload` = two dicts keyed by the same sub-keys
  (`KEY_*` in `const.py`: RS `last_60`/`next_60`/`next_60_120`/`next_120`/
  `peak_1h`, RADOLAN `amount`, HymecNG `precipitation_type`; RV keeps its
  own). `CoordinatorData` is typed `dict[str, Any]` /
  `dict[str, ProductMetadata | None]`, which covers the HymecNG `str` and the
  `None` metadata gaps.
- Descriptions name a `sub_key` instead of an `access_fn`; the RS indices,
  the per-description lambdas and `scalar_reading` are gone. The dry streak
  takes its sub-key from `_PAST_HOUR_KEY` by source; the totals and
  backfill read `amount`. `countable` stays: it filters NaN and negative
  values, which is not shape-related.
- *Deviation:* two parallel dicts rather than `Mapping[str, Reading(value,
  meta)]`. RV's `attrs_fn`s read sibling values (`start_in`, `start_at`, ...)
  from the whole data dict, and a value may have no metadata
  (`rain_events`). Wrapping each value would have touched every RV
  description and the totals' restore path for no gain. The shared shape is
  now a stated contract (one sub-key indexes both) rather than a coincidence.
- No user-visible change: unique ids, states and attributes are as before
  (the integration tier's setup and sensor tests assert them).

## PR 8 — URLs, scripts, live tiers, duplicate fetches

*(TD 8, 12; S-altitude 1, 10; S-reuse 12, 15; S-efficiency 8)*

- `radar/urls.py` (HA-free): `product_url(key, ts)`, `member_prefix(key, ts)`;
  used by products, `check_release_delay.py`, `compare_rw_runs.py`,
  `create_fixture.py`, both live tiers. Parity test against every class's `_get_url`.
- Release-delay monitor adds RV and `sf_2350`; drift-guard test
  parametrised over all `PRODUCT_CLASSES`.
- `compare_rw_runs.py` imports `utils.async_get`, `nowcast.LEADS`,
  `async_read_tar_members` instead of copies; shared `tests/live_common.py`.
- Live test for the production range-read path (requests ≤ N, no fallback).
- **Decision D2:** dedupe the fetches of the same file (`rw` and `rw_10min`
  at :00, 24×/day; `sf` and `sf_2350`, 1×/day).

**Step 8 outcome (3 commits `dbe65c0`..`4a06c68`; D2 open).**
- `radar/urls.py` holds every URL pattern; products derive theirs from
  `PRODUCT_KEY` (six `_get_url` overrides gone); probe, both scripts and both
  live tiers use it. Golden test spells out all seven URLs.
- Release-delay probe covers RV (live: 3m58s observed vs 4m10s); `sf_2350`
  pinned to SF's delay instead (same files); drift guard over all classes.
- Live test of RS's range read (no fallback, <= 6 requests; passes today).
- D2 done afterwards: `DownloadCache` (entry-scoped, 5 min, RADOLAN only). *Moved to step 9:* a shared
  `tests/live_common.py` for the duplicated candidate walks.

## PR 9 — Tests

*(TD 12, 17; S-reuse 13, 14)*

- Factories that build coordinators/entities through real constructors
  (replace `__new__` + private attributes).
- One fake range server in `tests/factories`; one `make_radvor_tar`;
  `nowcast.LEADS` instead of `range(0, 121, 5)` (~15×); `MockConfigEntry`
  fixtures in `tests/integration/conftest.py`; `hass_storage` instead of `_FakeStore`;
  direct `async_get_entity_id` lookups.
- Real RV and HymecNG fixture members; cover the "release already fetched" early return,
  fast-poll callback, dry-streak restore + downtime correction, migration refusal,
  RV fill glue. Split `test_products.py` per product.

**Step 9 outcome (done, 8 commits `c7291c7`..`6967476`).** Tests only; no
component code changed. Parser 166 -> 171, integration 239 -> 246,
reference 10 -> 12; both live tiers pass (4 and 55).
- `tests/factories/radvor.py`: `make_radvor_tar`, `radvor_archive`,
  `RangeServer` (ranges, ETag, If-Range; as `fetch` and as `async_get`)
  replace two tar builders, the tar_range server and three hand-rolled range
  responders; `range(0, 121, 5)` is `nowcast.LEADS` throughout.
- `tests/integration/conftest.py`: `make_entry` and `make_coordinator`
  (real constructor on the real hass, fetch jitter an input) replace 18
  hand-written entries and every coordinator `__new__`. Entries are titled
  "Home", so entity ids read `home_*`.
- Entities (sensors, binary sensor, total) come from their constructors.
  State goes in the way the code takes it (`_restore`, `_start_backfill`);
  the dry-streak anchor is the one value still set directly (restoring it
  needs a running entry). Setup tests look entities up by unique id.
- The rain-events glue runs on HA's real `Store` (`hass_storage`), with the
  tracker built by RV's own constructor; `_FakeStore` is gone. On the real
  hass the fill is an eager background task, which changed one assertion.
- `test_products.py` split into `test_product_rs/rv/hymecng/radolan`,
  `test_product_rv_rain_events` and a shared-concerns `test_products.py`,
  with `product_helpers.py`.
- Real RV analysis and HymecNG fixtures (`create_fixture.py --product`),
  tested in the parser, reference and integration tiers.
- New coverage: the already-fetched early return, and the fast-poll retry
  firing end to end (checked against a mutant). The other listed gaps
  (dry-streak restore + correction, migration refusal, RV fill glue) were
  covered by earlier steps.
- `tests/live_common.py`: the live tiers' release walk, on `ReleaseGrid`.

## PR 10 — Documentation

*(TD 13, 16)*

- CLAUDE.md Architecture lists every module (+ a test asserting it); README
  `next 1–2h` → `next 60–120 min`, new entities screenshot, remove orphan
  image; `tests/README.md` per tier by glob, not by name; one place for each
  figure (archive sizes, retry/grace timings, test asserting README timings).
- Release history out of CLAUDE.md into `CHANGELOG.md` + `docs/adr/`; old
  entity-id list as a constant checked by a test (single source for README too).

**Step 10 outcome (done, 5 commits `5058c0f`..`9eeced6`).**
- README: `next 1–2h` fixed; the orphan `screenshot_entities.png` removed;
  `test_docs.py` (integration) builds the troubleshooting timings from the
  constants and checks `sf_2350` is the only exception.
- CLAUDE.md Architecture lists every module (`radar/urls.py`,
  `radar/__init__.py` were missing; `const.py`/`utils.py` descriptions were
  stale), checked both ways by `tests/parser/test_docs.py`.
- `tests/entity_ids.py` is the one record of released ids; the setup test
  and a README check use it.
- `tests/README.md` describes tiers by naming pattern, and lists the
  helpers and every workflow.
- *Decision:* ADRs only, no `CHANGELOG.md` — Release Drafter writes the
  release notes from PRs. Eight records in `docs/adr/`; CLAUDE.md keeps the
  rules and cites them (40 lines shorter); a test checks the citations.
- *Not done:* a new entities screenshot. It needs a running HA on this
  branch; the README still shows the 2026.8.0 entity list.
- "One place for each figure": the README timings are tested against the
  constants; each measurement (archive sizes, publication delays) is stated
  once in CLAUDE.md or in an ADR. ADRs 0002 and 0004 both cite RW's ~25.7 min,
  each as the measurement its decision rested on; records are not edited.

---

## Decisions needed before the affected PR

| # | Question | Recommendation |
|---|---|---|
| D1 | Derive RS `next_60` / `next_60_120` / `next_120` from RV's rolling sums and range-read only RS `_000`? | **Decided: not now.** RS and RV stay independent; revisit after step 7 only if bandwidth matters. |
| D2 | How to dedupe the files fetched by two coordinators | **Decided: keep `rw_10min`, add the short-lived cache** (done, RADOLAN products only). |
| D3 | `ReleaseGrid` in a new HA-free module vs keeping the arithmetic on the coordinator | **Decided: new module**; the `ast` reading of class constants stays as is. |
| D4 | Move `rain_events.py` into `radar/` | **Decided and done** (step 6, `f6a99d5`). |
| D5 | Binary sensor: should `forecast_5min` follow the extra-attributes option? | **Decided: no, keep it always on** (deliberate per CLAUDE.md, documented unconditionally, automations may rely on it). Step 5 keeps it as an explicit exception. |
| D6 | `full_rolling_series` downloads the whole RS tar (1-5 GB/day). | **Decided: leave as is.** |
| D7 | Pyright in CI | **Decided: after step 7**, once the payload types are stable. |

**D7 outcome (done, 3 commits `61a80b1`..).** Pyright 1.1.414, basic mode,
on `custom_components/`, in a `typecheck` group (`ha-test` + pyright) and a
`typecheck` CI job. The first run had 349 errors: ~280 were one cause (the
shared sensor kwargs dicts inferred as a union), 34 HA's entity override
pattern (`reportIncompatibleVariableOverride`, turned off), and the rest were
fixed one by one. One real bug, fixed and tested on its own: a null `nodata`
entry in the rain-events store restored as None and then failed every save.
The only ignores are the config flow's three `Schema` arguments (probatio,
see CLAUDE.md "Checks"). Not covered yet: `scripts/` and `tests/`, and
standard mode.

## Sequencing and size

| PR | Depends on | Size | Risk |
|---|---|---|---|
| 1 Bug fixes | — | S-M | low (each tested) |
| 2 Guardrails | — | S | none |
| 3 Leaf cleanups | 2 | M (split ok) | low |
| 4 Core API | 3 | M | medium — timing code; jitter/grace tests guard it |
| 5 Options | 4 | M | medium — entity setup |
| 6 Rain events | 4 (5 helps) | M-L | medium — Store compatibility |
| 7 Payload shape | 5 | M | medium — touches every descriptor |
| 8 URLs/scripts | 4 | S-M | low |
| 9 Tests | 4-7 | M | none |
| 10 Docs | rolling | S | none |

PRs 1 and 2 can go in parallel right away; 8 and 9 can run alongside 5-7.
