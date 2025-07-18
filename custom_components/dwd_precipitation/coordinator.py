"""Data update coordinator for the dwd precipitation integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=120)


class UpdateCoordinator(DataUpdateCoordinator):
    """Data update coordinator."""

    def __init__(
            self,
            hass: HomeAssistant,
            entry: ConfigEntry,
            async_client,
            products,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=entry.data[CONF_NAME],
            update_interval=UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.async_client = async_client
        self.products = products

    async def _async_update_data(self) -> dict:
        """Update the data and the signal."""
        data = {}
        for product in self.products:
            if product.requires_update:
                await product.update(self.async_client)

            data[product.PRODUCT_KEY] = product.data

        return data