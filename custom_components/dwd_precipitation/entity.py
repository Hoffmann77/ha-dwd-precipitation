"""Shared base entity for the DWD Precipitation integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BaseProductUpdateCoordinator, ProductMetadata


@dataclass(frozen=True, kw_only=True)
class DwdEntityDescriptionMixin:
    """What a DWD entity reads, for every platform's entity description."""

    product_key: str
    # The key of this entity's value in the coordinator's data, and of its
    # ProductMetadata in the metadata (see CoordinatorData).
    sub_key: str
    # Companion attributes computed from the data payload. Always exposed
    # (not gated behind the diagnostic-attributes option).
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None
    # Like attrs_fn, but computed from this entity's ProductMetadata. Also
    # always exposed.
    metadata_attrs_fn: Callable[[ProductMetadata], dict[str, Any]] | None = None


def plain_value(value: Any) -> Any:
    """Return an attribute value as HA stores it: a datetime as an ISO string.

    Used on every companion attribute the descriptions compute. Everything else
    they pass is already a plain float, int, str or list, because the readers
    turn HDF5's bytes and numpy values into those, so it is returned as it is.

    """
    return value.isoformat() if isinstance(value, datetime) else value


def unique_id_for(entry_id: str, key: str) -> str:
    """Return the unique id of an entry's entity with description ``key``.

    The entry id plus the key, e.g. "<entry_id>_radvor_rs_000". Home Assistant
    uses the unique id to remember an entity's id, name and settings, so a
    released id must never change (it would orphan the user's entity), and the
    format lives here only.

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
        """Set up the entity's description, unique id and device.

        ``coordinator`` is the product the entity reads, ``description`` says
        what it shows (key, name, unit, sub-key). Every entity of an entry
        belongs to one service device named after the entry; its unique id is
        the entry id plus the description's key.

        """
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
        """Return whether the coordinator has a value recent enough to show.

        It asks the coordinator's data_is_reportable rather than whether the
        last update succeeded, so a value that ages out stops being shown even
        when no further fetch happens, and the entity and the update loop
        always agree. An unavailable entity shows "unavailable" in Home
        Assistant.

        """
        return self.coordinator.data_is_reportable

    @property
    def _description(self) -> DwdEntityDescriptionMixin:
        """Return the DWD part of this entity's description.

        Every platform's description includes DwdEntityDescriptionMixin
        (product key, sub-key, attribute functions), but HA types
        entity_description as the plain EntityDescription; this cast lets the
        code use those fields with their types.

        """
        return cast(DwdEntityDescriptionMixin, self.entity_description)

    def _value(self) -> Any:
        """Return the value this entity shows, from the coordinator's data.

        The coordinator holds one release's values in a dict; the description's
        sub_key picks this entity's from it. None while the coordinator has no
        data, or when the release had none for the location.

        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.data.get(self._description.sub_key)

    def _metadata(self) -> ProductMetadata | None:
        """Return this entity's ProductMetadata, if the coordinator has it.

        Picked by the same sub_key as the value. It says which product and
        release the value comes from, and the time window the value covers;
        None while the coordinator has no data or the value has no metadata.

        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.metadata.get(self._description.sub_key)

    def _described_attributes(self) -> dict[str, Any]:
        """Return the attributes the description adds to the entity.

        ``attrs_fn`` computes companion values from the payload (the minutes
        until rain, say), ``metadata_attrs_fn`` from the metadata (the data
        window, say). Both are always shown, unlike the opt-in diagnostic
        attributes, and every value is made storable with plain_value. Empty
        while the coordinator has no data.

        """
        attrs: dict[str, Any] = {}
        if self.coordinator.data is None:
            return attrs

        description = self._description
        data = self.coordinator.data.data
        if description.attrs_fn is not None:
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
