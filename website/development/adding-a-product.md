---
title: Adding a DWD product
description: The checklist for adding another DWD radar product to the integration.
---

Each DWD product is one coordinator subclass in `products.py`. Adding one
touches a handful of places, in this order.

## Checklist

1. **Subclass a base** in `products.py`:
   - `WholeFileProduct` for one file per release, decoded whole (HymecNG,
     RADOLAN);
   - `RadvorProduct` for a RADVOR tar archive (RS, RV);
   - `BaseProductUpdateCoordinator` itself only if neither fits.
2. **Set the class constants:** `PRODUCT_KEY`, `PRODUCT_LABEL`,
   `RELEASE_INTERVAL`, `RELEASE_DELAY`, `RELEASE_OFFSET` and `OVERDUE_GRACE`
   (spelled out even when it is `DEFAULT_OVERDUE_GRACE`; a test enforces
   it), `COVERAGE_KEYS` (the sub-keys that are `None` without data for the
   cell; a test checks every product has them), and `MAX_FAST_POLL_INTERVAL`
   if the default does not fit. See [below](#picking-the-release-constants).
3. **Add the URL pattern** to `radar/urls.py`; `_get_url` derives the URL from
   `PRODUCT_KEY`.
   - A `WholeFileProduct` implements the blocking `_parse(content, ts)`; the
     base downloads the file and runs it in the executor.
   - A `RadvorProduct` implements `_fetch_and_parse`.
   - Keep `_fetch_and_parse` free of side effects; anything else goes in
     `_async_on_new_release`.
4. **The grid** comes from each file's `/where` group (`radar/grid.py`), so a
   product on another polar-stereographic grid needs nothing more; one in
   another projection needs that projection in `grid.py`.
5. **Add sensor descriptions** in `sensor.py` (a new `*_SENSORS` tuple).
6. **Register the class** in the `PRODUCT_CLASSES` tuple of `__init__.py`.
7. **Register the sensors** in `async_setup_entry` of `sensor.py`, and add
   each `translation_key`'s name to `translations/en.json` and
   `translations/de.json`. The two files must keep identical keys; a test
   checks it.
8. **Add it to `PRODUCTS`** in `scripts/check_release_delay.py`, so its
   `RELEASE_DELAY` is checked against what DWD actually does.
9. **Document it**: an entity page in `website/docs/entities/` and its German
   translation, and the tables in the introduction, the entity overview and
   [Release timing](/how-it-works/release-timing).

## Picking the release constants

- **`RELEASE_INTERVAL` and `RELEASE_OFFSET`** describe the nominal times:
  every 5 minutes at :00, :05, … is an interval of 5 minutes and no offset;
  hourly at :50 is an interval of 1 hour and an offset of 50 minutes.
- **`RELEASE_DELAY`** is how long after its nominal time a file is on Open
  Data. Measure it from the `Last-Modified` headers of recent files (that is
  what `scripts/check_release_delay.py` does) and take a value at or above
  the mean: fetching before DWD publishes costs a failed request and a retry
  every time.
- **`OVERDUE_GRACE`** is how long DWD is given to publish an overdue release
  before the sensors go stale. It must not be a whole multiple of
  `RELEASE_INTERVAL`, or the deadline coincides with a fetch; a test enforces
  that per product.
- **`USE_LOCAL_TIME`** is for a product whose nominal times are on local
  time, like the daily `sf_2350`.

## Naming the entities

Follow the naming rules in `CLAUDE.md` and
[ADR 0001](/development/adr/0001-entity-names-state-their-window): a window in
the name only when it is part of the value, `last` / `next` / calendar
periods, units that follow the product. Never give a new entity an id a
released version gave another one; `tests/entity_ids.py` records them.
