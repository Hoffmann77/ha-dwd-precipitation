"""Fixtures for the dwd_precipitation test suite."""

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = "pytest_homeassistant_custom_component"

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
        """Enable custom integrations for every test that uses the hass fixture."""
except ImportError:
    # When running without homeassistant (e.g. the parser/reference/live jobs),
    # skip the integration tier, which imports HA packages. parser/, reference/
    # and live/ are HA-free and collect fine.
    collect_ignore_glob = ["integration/*"]
