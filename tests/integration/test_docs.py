"""The figures the README states, against the code they describe."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from custom_components.dwd_precipitation import PRODUCT_CLASSES
from custom_components.dwd_precipitation.coordinator import (
    DEFAULT_OVERDUE_GRACE,
    FAST_POLL_START,
    BaseProductUpdateCoordinator,
)
from custom_components.dwd_precipitation.products import RadolanSFLastYesterday

README = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")


def _spoken(delta: timedelta) -> str:
    """A duration as the README writes it: "60 seconds", "5 minutes"."""
    seconds = int(delta.total_seconds())
    if seconds % 60 or seconds <= 60:
        return f"{seconds} seconds"
    return f"{seconds // 60} minutes"


def test_readme_states_the_retry_and_grace_timings():
    """Troubleshooting: when retries start and stop, and when a sensor gives up."""
    daily = RadolanSFLastYesterday
    retries = (
        f"starting after {_spoken(FAST_POLL_START)} and backing off to at most "
        f"{_spoken(BaseProductUpdateCoordinator.MAX_FAST_POLL_INTERVAL)} "
        f"({_spoken(daily.MAX_FAST_POLL_INTERVAL)} for `Precipitation yesterday`)"
    )
    grace = (
        f"more than {_spoken(DEFAULT_OVERDUE_GRACE)} overdue "
        f"({_spoken(daily.OVERDUE_GRACE)} for `Precipitation yesterday`)"
    )
    assert retries in README
    assert grace in README


def test_the_daily_product_is_the_only_exception_the_readme_names():
    """Every other product retries and waits as the README's general rule says."""
    for cls in PRODUCT_CLASSES:
        if cls is RadolanSFLastYesterday:
            continue
        assert (
            cls.MAX_FAST_POLL_INTERVAL
            == BaseProductUpdateCoordinator.MAX_FAST_POLL_INTERVAL
        ), cls.__name__
        assert cls.OVERDUE_GRACE == DEFAULT_OVERDUE_GRACE, cls.__name__
