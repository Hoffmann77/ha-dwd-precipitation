"""The Heat pump Signal integration."""

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.core import HomeAssistant

from .coordinator import UpdateCoordinator
from .const import (
    DOMAIN, PLATFORMS,
)

from .products import (
    RadvorRQ, RadolanRW, RadolanSF, RadolanSFLastYesterday
)

_LOGGER = logging.getLogger(__name__)

type MyConfigEntry = ConfigEntry[MyData]


@dataclass
class MyData:
    """Runtime data definition."""

    coordinator: UpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enphase Gateway from a config entry."""
    client = get_async_client(hass)

    lat = entry.data["latitude"]
    lon = entry.data["longitude"]

    products = (
        RadvorRQ(lat, lon),
        RadolanRW(lat, lon),
        RadolanSF(lat, lon),
        RadolanSFLastYesterday(lat, lon),
    )

    coordinator = UpdateCoordinator(hass, entry, client, products)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = MyData(coordinator)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle config_entry updates."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entries."""
    unload = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload