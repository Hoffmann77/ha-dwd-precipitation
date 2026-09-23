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

    @property
    def available(self) -> bool:
        """Return True if the coordinator holds a value recent enough to show.

        Asking the coordinator what it is willing to report, rather than taking
        last_update_success at face value, means a value that quietly ages out
        stops being reported even if no further fetch is attempted. The rule
        itself lives on the coordinator so the entity and the update loop cannot
        answer this question differently.
        """
        return self.coordinator.data_is_reportable
