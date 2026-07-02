"""The DWD Precipitation integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import BaseProductUpdateCoordinator
from .const import PLATFORMS
from .products import RadvorRS, RadolanRW, RadolanSF, RadolanSFLastYesterday

_LOGGER = logging.getLogger(__name__)

type MyConfigEntry = ConfigEntry[MyData]


@dataclass
class MyData:
    """Runtime data definition."""

    coordinators: dict[str, BaseProductUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DWD Precipitation from a config entry."""
    client = async_get_clientsession(hass)

    lat = entry.data["latitude"]
    lon = entry.data["longitude"]

    product_coordinators: list[BaseProductUpdateCoordinator] = [
        RadvorRS(hass, entry, client, lat, lon),
        RadolanRW(hass, entry, client, lat, lon),
        RadolanSF(hass, entry, client, lat, lon),
        RadolanSFLastYesterday(hass, entry, client, lat, lon),
    ]

    keyed: dict[str, BaseProductUpdateCoordinator] = {}

    for coordinator in product_coordinators:
        await coordinator.async_config_entry_first_refresh()

        def make_callback(coord: BaseProductUpdateCoordinator):
            async def _callback(_now) -> None:
                await coord.async_refresh()
            return _callback

        for arg in coordinator.track_time_change_args:
            unsub = async_track_utc_time_change(
                hass,
                make_callback(coordinator),
                hour=arg["hour"],
                minute=arg["minute"],
                second=arg["second"],
            )
            entry.async_on_unload(unsub)

        keyed[coordinator.PRODUCT_KEY] = coordinator

    entry.runtime_data = MyData(keyed)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
