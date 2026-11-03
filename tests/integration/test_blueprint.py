"""The blueprint "DWD Regenwarnung" on a rain warning's status sensor.

Runs the blueprint in Home Assistant against a status sensor whose states and
attributes the test sets, and checks which actions run with which text.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import timedelta
from pathlib import Path

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service, async_fire_time_changed

BP = Path(__file__).parents[2] / "blueprints/automation/dwd/dwd_regenwarnung.yaml"
S = "sensor.home_waesche_rain_warning_status"

def attrs(peak10, start=20, length=35, typ=None, exp=None, open_end=False):
    now = dt_util.utcnow()
    st = now + timedelta(minutes=start)
    return {"event_id": "e1", "start": st.isoformat(), "end": (st + timedelta(minutes=length)).isoformat(),
            "beyond_horizon": open_end, "mm": 1.2, "peak_1h": peak10 * 3, "peak_10min": peak10,
            "type": typ, "expected_type": exp}

DRY = {k: None for k in attrs(0)}

async def settle():
    """Let the automation run; a waiting run would block async_block_till_done."""
    for _ in range(50):
        await asyncio.sleep(0)

async def setup(hass, push_thr=0, ann_thr=0, extra=None):
    d = Path(hass.config.path("blueprints/automation/dwd")); d.mkdir(parents=True, exist_ok=True); shutil.copy(BP, d)
    hass.states.async_set(S, "dry", DRY)
    push = async_mock_service(hass, "test", "push"); ann = async_mock_service(hass, "test", "announce")
    inp = {"warning_sensor": S,
           "push_actions": [{"action": "test.push", "data": {"message": "{{ message_text }}"}}],
           "announce_actions": [{"action": "test.announce", "data": {"message": "{{ message_text }}"}}],
           "announce_after": "00:00:00", "announce_before": "00:00:00",
           "push_min_intensity": push_thr, "announce_min_intensity": ann_thr}
    inp.update(extra or {})
    assert await async_setup_component(hass, "automation", {"automation": {"id": "x", "use_blueprint": {
        "path": "dwd/dwd_regenwarnung.yaml", "input": inp}}})
    await settle()
    return push, ann

async def step(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes)); async_fire_time_changed(hass); await settle()

async def test_soon_text_with_expected_type_and_length(hass, freezer):
    push, ann = await setup(hass)
    hass.states.async_set(S, "soon", attrs(0.3, 20, 35, exp="snow")); await settle()
    assert len(push) == 1 and len(ann) == 1
    assert push[0].data["message"] == "In 20 Minuten beginnt leichter Schneefall für 35 Minuten."

async def test_rain_text_and_open_end(hass, freezer):
    push, ann = await setup(hass)
    hass.states.async_set(S, "rain", attrs(1.0, -5, 50, typ="rain", exp="rain", open_end=True)); await settle()
    assert push[0].data["message"] == "Es regnet bereits, voraussichtlich mindestens 45 Minuten."

async def test_rain_text_with_end(hass, freezer):
    push, ann = await setup(hass)
    hass.states.async_set(S, "rain", attrs(1.0, -5, 25, typ="drizzle", exp="drizzle")); await settle()
    assert push[0].data["message"] == "Es nieselt bereits, noch etwa 20 Minuten."

async def test_unknown_type_and_intensity_level(hass, freezer):
    push, ann = await setup(hass)
    hass.states.async_set(S, "soon", attrs(2.0, 1, 30)); await settle()   # 12 mm/h
    assert push[0].data["message"] == "In wenigen Minuten beginnt starker Niederschlag für 30 Minuten."

async def test_per_channel_threshold(hass, freezer):
    push, ann = await setup(hass, 0, 1.0)
    hass.states.async_set(S, "soon", attrs(0.1, 20, exp="drizzle")); await settle()   # 0.6 mm/h
    assert len(push) == 1 and len(ann) == 0
    await step(hass, freezer, 5)
    hass.states.async_set(S, "soon", attrs(0.5, 15, exp="rain")); await settle()   # 3 mm/h
    assert len(push) == 1 and len(ann) == 1
    assert ann[0].data["message"] == "In 15 Minuten beginnt mäßiger Regen für 35 Minuten."

async def test_drizzle_only_then_new_event_after_dry_time(hass, freezer):
    push, ann = await setup(hass, 1.0, 1.0)
    hass.states.async_set(S, "soon", attrs(0.1)); await settle()
    hass.states.async_set(S, "rain", attrs(0.1, -1)); await settle()
    hass.states.async_set(S, "dry", DRY); await settle()
    assert len(push) == 0
    await step(hass, freezer, 16)
    hass.states.async_set(S, "soon", attrs(1.0)); await settle()
    assert len(push) == 1 and len(ann) == 1

async def test_defaults_many_events(hass, freezer):
    freezer.move_to("2026-10-27 08:00:00+00:00")
    d = Path(hass.config.path("blueprints/automation/dwd")); d.mkdir(parents=True, exist_ok=True); shutil.copy(BP, d)
    hass.states.async_set(S, "dry", DRY)
    pn = async_mock_service(hass, "notify", "persistent_notification")
    assert await async_setup_component(hass, "automation", {"automation": {"id": "x", "use_blueprint": {
        "path": "dwd/dwd_regenwarnung.yaml", "input": {"warning_sensor": S}}}})
    await settle()
    for i in range(4):
        hass.states.async_set(S, "soon", attrs(0.3, 30)); await settle()
        await step(hass, freezer, 30)
        hass.states.async_set(S, "rain", attrs(0.3, 0)); await settle()
        await step(hass, freezer, 40)
        hass.states.async_set(S, "dry", DRY); await settle()
        await step(hass, freezer, 30)
        assert len(pn) == i + 1
