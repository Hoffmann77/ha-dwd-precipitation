"""Dependency drift guards: what users install vs. what the tiers test.

Lives in the integration tier because that is the environment HA installs:
its numpy is HA's own pin, its h5py the one the manifest pulls in.
"""

from __future__ import annotations

import json
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _group_pin(group: str, package: str) -> str:
    """Return the ``==`` version a dependency group pins ``package`` to."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for requirement in pyproject["dependency-groups"][group]:
        if (match := re.fullmatch(rf"{package}==(\S+)", requirement)) is not None:
            return match.group(1)
    raise AssertionError(f"{group} does not pin {package}")


def test_parser_tier_decodes_with_has_numpy() -> None:
    """A HA update that moves numpy fails here: update the unit-test pin."""
    assert _group_pin("unit-test", "numpy") == version("numpy")


def test_manifest_h5py_floor_is_the_tested_version() -> None:
    """Users get at least the h5py every tier tests (Renovate moves both)."""
    manifest = json.loads(
        (ROOT / "custom_components/dwd_precipitation/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    floors = [r.removeprefix("h5py>=") for r in manifest["requirements"] if r.startswith("h5py")]
    assert floors == [version("h5py")] == [_group_pin("ha-test", "h5py")]
