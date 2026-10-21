"""Factories for the integration tier: config entries and coordinators.

Everything is built through the real constructors on the real ``hass``, so a
test breaks when the constructor changes rather than passing on state it set
up by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dwd_precipitation import coordinator as coordinator_mod
from custom_components.dwd_precipitation.const import DOMAIN
from custom_components.dwd_precipitation.coordinator import (
    BaseProductUpdateCoordinator,
    CoordinatorData,
)

LAT, LON = 51.05, 13.73
ENTRY_DATA = {"name": "Home", "latitude": LAT, "longitude": LON}

MakeEntry = Callable[..., MockConfigEntry]
MakeCoordinator = Callable[..., Any]


@pytest.fixture
def make_entry(hass) -> MakeEntry:
    """Return a factory for a "Home" config entry, already added to hass.

    Keyword arguments go to MockConfigEntry (version, minor_version, ...).
    """

    def _make(options: dict[str, Any] | None = None, **kwargs: Any) -> MockConfigEntry:
        kwargs.setdefault("title", "Home")
        entry = MockConfigEntry(
            domain=DOMAIN, data=dict(ENTRY_DATA), options=options or {}, **kwargs
        )
        entry.add_to_hass(hass)
        return entry

    return _make


@pytest.fixture
def make_coordinator(hass, make_entry) -> MakeCoordinator:
    """Return a factory for a product coordinator, built by its constructor.

    ``jitter`` is the fetch jitter the entry would derive (0 by default, so
    schedules read as the product's constants). ``data`` and ``curr_release``
    stand for a release fetched earlier.
    """

    def _make(
        cls: type[BaseProductUpdateCoordinator],
        options: dict[str, Any] | None = None,
        *,
        entry: MockConfigEntry | None = None,
        jitter: timedelta = timedelta(),
        data: CoordinatorData | None = None,
        curr_release: datetime | None = None,
    ):
        entry = entry or make_entry(options)
        with patch.object(coordinator_mod, "fetch_jitter_for", return_value=jitter):
            coordinator = cls(hass, entry, object(), LAT, LON)
        coordinator.data = data
        coordinator.curr_release = curr_release
        return coordinator

    return _make
