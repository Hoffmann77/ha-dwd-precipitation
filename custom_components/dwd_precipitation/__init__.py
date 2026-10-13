"""The DWD Precipitation integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import BaseProductUpdateCoordinator
from .options import DwdOptions
from .utils import DownloadCache
from .const import CONF_DRY_STREAK_SOURCE, LEGACY_DRY_STREAK_SOURCE, PLATFORMS
from .rain_events_tracker import RainEventsTracker
from .products import (
    RadvorRS,
    RadvorRV,
    HymecNG,
    RadolanRW,
    RadolanRW10,
    RadolanSF,
    RadolanSFLastYesterday,
)

PRODUCT_CLASSES: tuple[type[BaseProductUpdateCoordinator], ...] = (
    RadvorRS,
    RadvorRV,
    HymecNG,
    RadolanRW,
    RadolanRW10,
    RadolanSF,
    RadolanSFLastYesterday,
)

_LOGGER = logging.getLogger(__name__)

# How long a shared download is kept: two products fetch the same release
# within their fetch jitter (<= 30 s) of each other; a few minutes also
# covers one of them retrying after a 404. RADOLAN files are ~30 KB.
SHARED_DOWNLOAD_TTL = timedelta(minutes=5)

type MyConfigEntry = ConfigEntry[MyData]


@dataclass
class MyData:
    """Runtime data definition."""

    coordinators: dict[str, BaseProductUpdateCoordinator]
    options: DwdOptions


async def async_setup_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    """Set up DWD Precipitation from a config entry."""
    client = async_get_clientsession(hass)

    lat = entry.data["latitude"]
    lon = entry.data["longitude"]

    # Products that exist for one option are only built when it is in use, so
    # an entry never fetches what none of its entities show.
    options = DwdOptions.from_options(entry.options)
    product_coordinators: list[BaseProductUpdateCoordinator] = [
        cls(hass, entry, client, lat, lon)
        for cls in PRODUCT_CLASSES
        if cls.is_needed(options)
    ]
    # Products that read the same files share one download of each.
    downloads = DownloadCache(SHARED_DOWNLOAD_TTL.total_seconds())
    for coordinator in product_coordinators:
        coordinator.download_cache = downloads

    # Refresh every product concurrently. async_refresh() records a failure on
    # the coordinator instead of raising, so one dead product cannot veto the
    # whole entry — each failed coordinator keeps its own fast-poll retry ramp
    # running and its entities simply start out unavailable. Only a clean sweep
    # of failures means the entry itself is not ready.
    await asyncio.gather(
        *(coordinator.async_refresh() for coordinator in product_coordinators)
    )

    failed = [
        c.PRODUCT_LABEL or c.PRODUCT_KEY
        for c in product_coordinators
        if not c.last_update_success
    ]

    if len(failed) == len(product_coordinators):
        raise ConfigEntryNotReady(
            "No data could be fetched from DWD OpenData. Either this Home "
            "Assistant has no internet access right now, or DWD OpenData is "
            "down; setup will be retried automatically."
        )

    if failed:
        _LOGGER.warning(
            "Started without the DWD %s product(s): DWD OpenData did not serve "
            "them just now. Every other product is working, and the missing "
            "ones are retried automatically in the background; no action is "
            "needed unless their sensors stay unavailable",
            ", ".join(sorted(failed)),
        )

    for coordinator in product_coordinators:
        coordinator.async_track_releases()

    if not options.rain_events:
        # Turned off: drop what the tracker stored, so turning it on again
        # starts clean rather than from a state days out of date.
        await RainEventsTracker.async_remove(hass, entry.entry_id)

    entry.runtime_data = MyData(
        {c.PRODUCT_KEY: c for c in product_coordinators}, options
    )
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an older config entry to the current version."""
    if entry.version > 1:
        # Written by a newer major version; HA refuses to load it either way.
        return False

    if entry.minor_version < 2:
        # 1.2 added the dry-streak source. Pin entries that predate it to the
        # product they have always counted, so an upgrade changes nothing.
        options = {**entry.options}
        options.setdefault(CONF_DRY_STREAK_SOURCE, LEGACY_DRY_STREAK_SOURCE)
        hass.config_entries.async_update_entry(
            entry, options=options, minor_version=2
        )

    return True


async def update_listener(hass: HomeAssistant, entry: MyConfigEntry) -> None:
    """Handle config entry updates."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete what the entry stored when it is removed."""
    await RainEventsTracker.async_remove(hass, entry.entry_id)
