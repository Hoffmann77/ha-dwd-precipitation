"""The DWD Precipitation integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .coordinator import BaseProductUpdateCoordinator
from .const import CONF_DRY_STREAK_SOURCE, LEGACY_DRY_STREAK_SOURCE, PLATFORMS
from .products import (
    RAIN_EVENTS_STORE_VERSION,
    rain_events_enabled,
    rain_events_store_key,
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

type MyConfigEntry = ConfigEntry[MyData]


@dataclass
class MyData:
    """Runtime data definition."""

    coordinators: dict[str, BaseProductUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    """Set up DWD Precipitation from a config entry."""
    client = async_get_clientsession(hass)

    lat = entry.data["latitude"]
    lon = entry.data["longitude"]

    # Products that exist for one option are only built when it is in use, so
    # an entry never fetches what none of its entities show.
    product_coordinators: list[BaseProductUpdateCoordinator] = [
        cls(hass, entry, client, lat, lon)
        for cls in PRODUCT_CLASSES
        if cls.is_needed(entry.options)
    ]

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

    if not rain_events_enabled(entry.options):
        # Turned off: drop what the tracker stored, so turning it on again
        # starts clean rather than from a state days out of date.
        await Store(
            hass, RAIN_EVENTS_STORE_VERSION, rain_events_store_key(entry.entry_id)
        ).async_remove()

    entry.runtime_data = MyData({c.PRODUCT_KEY: c for c in product_coordinators})
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
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Write rain_events now: an options change reloads the entry, and the new
    # coordinator must read the current state, not one a pending save still
    # holds.
    rv = entry.runtime_data.coordinators.get(RadvorRV.PRODUCT_KEY)
    if isinstance(rv, RadvorRV):
        await rv.async_save_rain_events()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete what the entry stored when it is removed."""
    await Store(
        hass, RAIN_EVENTS_STORE_VERSION, rain_events_store_key(entry.entry_id)
    ).async_remove()
