"""Shared base entity for the DWD Precipitation integration."""

from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BaseProductUpdateCoordinator


class DwdCoordinatorEntity(CoordinatorEntity[BaseProductUpdateCoordinator]):
    """Base coordinator entity shared by all DWD Precipitation platforms."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title or "DWD Precipitation",
        )
