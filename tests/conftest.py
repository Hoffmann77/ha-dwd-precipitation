"""Fixtures for the dwd_precipitation test suite.

pytest-home-assistant registers itself through its pytest11 entry point and
enables custom integrations for every ``hass`` test, so nothing is wired up
here when it is installed.
"""

try:
    import pytest_homeassistant  # noqa: F401
except ImportError:
    # When running without homeassistant (e.g. the parser/reference/live jobs),
    # skip the integration tier, which imports HA packages. parser/, reference/
    # and live/ are HA-free and collect fine.
    collect_ignore_glob = ["integration/*"]
