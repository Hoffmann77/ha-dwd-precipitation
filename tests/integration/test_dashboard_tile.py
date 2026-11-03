"""The dashboard tile "DWD Regenwarnung": its templates on a rain warning.

Renders every template of the tile against a status sensor and the location's
"Precipitation expected" sensor with its 5-minute forecast.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import yaml
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

TILE = Path(__file__).parents[2] / "dashboards/dwd_regenwarnung_kachel.yaml"
S = "sensor.home_waesche_rain_warning_status"
B = "binary_sensor.home_precipitation_expected"
W = "binary_sensor.home_waesche_rain_warning"


def forecast(now, wet_from=4):
    out = []
    for i in range(25):
        st = now + timedelta(minutes=5 * i - 5)
        out.append({"start": st.isoformat(), "end": (st + timedelta(minutes=5)).isoformat(),
                    "amount": 0.1, "intensity": 1.2 if i >= wet_from else 0.0})
    return out


async def _setup(hass):
    """Register the entities on a DWD entry, plus another location's forecast.

    integration_entities() finds a loaded integration's entities through its
    platforms; with only registry entries here it falls back to entries whose
    title is the name asked for, hence the title.

    """
    entry = MockConfigEntry(domain="dwd_precipitation", title="dwd_precipitation"); entry.add_to_hass(hass)
    reg = er.async_get(hass)
    for eid in (S, B, W):
        domain, obj = eid.split(".")
        reg.async_get_or_create(domain, "dwd_precipitation", obj, suggested_object_id=obj, config_entry=entry)
    other = MockConfigEntry(domain="dwd_precipitation", title="dwd_precipitation"); other.add_to_hass(hass)
    reg.async_get_or_create("binary_sensor", "dwd_precipitation", "x", suggested_object_id="work_precipitation_expected", config_entry=other)


def render_all(hass):
    card = yaml.safe_load(TILE.open())
    out = {}
    for key in ("icon", "primary", "secondary", "color", "badge_icon", "badge_color"):
        out[key] = " ".join(Template(card[key], hass).async_render({"entity": S}, parse_result=False).split())
    out["style"] = " ".join(Template(card["card_mod"]["style"], hass).async_render({"config": {"entity": S}}, parse_result=False).split())
    return out


async def test_tile_soon(hass):
    await _setup(hass)
    now = dt_util.utcnow()
    hass.states.async_set(B, "on", {"forecast_5min": forecast(now)})
    hass.states.async_set("binary_sensor.work_precipitation_expected", "on", {"forecast_5min": []})
    st = now + timedelta(minutes=4, seconds=40)
    hass.states.async_set(S, "soon", {"start": st.isoformat(), "end": (st + timedelta(minutes=35)).isoformat(),
        "beyond_horizon": False, "mm": 1.0, "peak_1h": 1.0, "peak_10min": 0.5, "type": None, "expected_type": "snow"})
    r = render_all(hass)
    assert r["primary"] == "In 5 Minuten beginnt Regen für 35 Minuten."
    assert r["secondary"].startswith("Bald: mäßiger Schneefall · Start in 5 Min.")
    assert r["color"] == "white"
    assert r["icon"] == "mdi:weather-rainy"
    assert "linear-gradient" in r["style"]


async def test_tile_dry_with_later_rain_and_rain(hass):
    await _setup(hass)
    now = dt_util.utcnow()
    hass.states.async_set(B, "on", {"forecast_5min": forecast(now, wet_from=13)})
    none = dict.fromkeys(["start", "end", "beyond_horizon", "mm", "peak_1h", "peak_10min", "type", "expected_type"])
    hass.states.async_set(S, "dry", none)
    r = render_all(hass)
    assert r["primary"] == "Nächster Regen in 1 Std."
    assert r["icon"] == "mdi:weather-cloudy"
    st = now - timedelta(minutes=10)
    hass.states.async_set(S, "rain", {"start": st.isoformat(), "end": (now + timedelta(minutes=20, seconds=10)).isoformat(),
        "beyond_horizon": True, "mm": 3.0, "peak_1h": 2.0, "peak_10min": 0.3, "type": "rain", "expected_type": "rain"})
    r = render_all(hass)
    assert r["primary"] == "Es regnet noch mindestens 20 Minuten."
    assert r["secondary"].startswith("Jetzt: leichter Regen")
    assert r["icon"] == "mdi:weather-pouring"
