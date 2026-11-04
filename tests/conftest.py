"""Fixtures for the dwd_precipitation test suite."""

try:
    # pytest-homeassistant loads itself (a pytest11 entry point), and its hass
    # fixture enables custom integrations by default; the import only tells
    # whether HA is installed.
    import pytest_homeassistant  # noqa: F401
except ImportError:
    # When running without homeassistant (e.g. the parser/reference/live jobs),
    # skip the integration tier, which imports HA packages. parser/, reference/
    # and live/ are HA-free and collect fine.
    # The directory, not its files: its conftest.py imports HA too.
    collect_ignore = ["integration"]
