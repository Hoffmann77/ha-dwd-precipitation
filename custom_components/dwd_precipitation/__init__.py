"""The DWD Precipitation integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import BaseProductUpdateCoordinator
from .const import PLATFORMS
from .products import (
    RadvorRS,
    RadvorRV,
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadolanSFLastYesterday,
)

PRODUCT_CLASSES: tuple[type[BaseProductUpdateCoordinator], ...] = (
    RadvorRS,
    RadvorRV,
    HymecNG,
    RadolanRW,
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

    product_coordinators: list[BaseProductUpdateCoordinator] = [
        cls(hass, entry, client, lat, lon) for cls in PRODUCT_CLASSES
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

    entry.runtime_data = MyData({c.PRODUCT_KEY: c for c in product_coordinators})
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, entry: MyConfigEntry) -> None:
    """Handle config entry updates."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
