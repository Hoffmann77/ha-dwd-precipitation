"""Shared base entity for the DWD Precipitation integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BaseProductUpdateCoordinator, ProductMetadata


@dataclass(frozen=True, kw_only=True)
class DwdEntityDescriptionMixin:
    """What a DWD entity reads, for every platform's entity description."""

    product_key: str
    # Picks this entity's value out of the coordinator's data (and its
    # ProductMetadata out of the metadata, which has the same shape).
    access_fn: Callable[[Any], Any]
    # Companion attributes computed from the data payload. Always exposed
    # (not gated behind the diagnostic-attributes option).
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None
    # Like attrs_fn, but computed from this entity's ProductMetadata. Also
    # always exposed.
    metadata_attrs_fn: Callable[[ProductMetadata], dict[str, Any]] | None = None


def plain_value(value: Any) -> Any:
    """Return values suitable for Home Assistant state attributes."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "decode"):
        return value.decode()
    if hasattr(value, "item"):
        return value.item()
    return value


def unique_id_for(entry_id: str, key: str) -> str:
    """Return the unique id of an entry's entity with description ``key``.

    Released ids must never change (it would orphan the user's entity), so
    the format lives here only.
    """
    return f"{entry_id}_{key}"


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
        self._attr_unique_id = unique_id_for(
            coordinator.config_entry.entry_id, description.key
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

    def _value(self) -> Any:
        """Return what the description picks from the data, None without data."""
        if self.coordinator.data is None or self.coordinator.data.data is None:
            return None
        return self.entity_description.access_fn(self.coordinator.data.data)

    def _metadata(self) -> ProductMetadata | None:
        """Return this entity's ProductMetadata, if the coordinator has it."""
        if self.coordinator.data is None or not self.coordinator.data.metadata:
            return None
        return self.entity_description.access_fn(self.coordinator.data.metadata)

    def _described_attributes(self) -> dict[str, Any]:
        """Return the description's companion and metadata attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data is None:
            return attrs

        description = self.entity_description
        data = self.coordinator.data.data
        if description.attrs_fn is not None and data is not None:
            attrs.update(
                {k: plain_value(v) for k, v in description.attrs_fn(data).items()}
            )
        metadata = self._metadata()
        if description.metadata_attrs_fn is not None and metadata is not None:
            attrs.update(
                {
                    k: plain_value(v)
                    for k, v in description.metadata_attrs_fn(metadata).items()
                }
            )
        return attrs
