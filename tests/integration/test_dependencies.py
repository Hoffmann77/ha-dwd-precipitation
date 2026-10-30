"""Dependency drift guards: what users install vs. what the tiers test.

Lives in the integration tier because that is the environment HA installs:
its numpy is HA's own pin, its h5py the one the manifest pulls in.

"HA's own pin" is HA's package_constraints.txt, which pytest-home-assistant
does not apply (its predecessor pytest-homeassistant-custom-component pinned
numpy itself), so the ha-test group pins numpy explicitly and the guard below
checks that pin against the constraints file rather than taking the installed
numpy on trust.
"""

from __future__ import annotations

import json
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import homeassistant

ROOT = Path(__file__).parents[2]


def _group_pin(group: str, package: str) -> str:
    """Return the ``==`` version a dependency group pins ``package`` to."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for requirement in pyproject["dependency-groups"][group]:
        if (match := re.fullmatch(rf"{package}==(\S+)", requirement)) is not None:
            return match.group(1)
    raise AssertionError(f"{group} does not pin {package}")


def _ha_constraint(package: str) -> str:
    """Return the ``==`` version HA's own package constraints pin ``package`` to.

    These are what HA installs integration requirements against; the
    homeassistant wheel ships them but does not depend on them, so nothing
    applies them to this environment unless the groups pin them too.
    """
    constraints = Path(homeassistant.__file__).with_name("package_constraints.txt")
    for line in constraints.read_text(encoding="utf-8").splitlines():
        if (match := re.fullmatch(rf"{package}==(\S+)", line.strip())) is not None:
            return match.group(1)
    raise AssertionError(f"HA does not constrain {package}")


def test_tiers_decode_with_has_numpy() -> None:
    """A HA update that moves numpy fails here: update both group pins."""
    assert (
        _group_pin("unit-test", "numpy")
        == _group_pin("ha-test", "numpy")
        == version("numpy")
        == _ha_constraint("numpy")
    )


def test_manifest_h5py_floor_is_the_tested_version() -> None:
    """Users get at least the h5py every tier tests (Renovate moves both)."""
    manifest = json.loads(
        (ROOT / "custom_components/dwd_precipitation/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    floors = [r.removeprefix("h5py>=") for r in manifest["requirements"] if r.startswith("h5py")]
    assert floors == [version("h5py")] == [_group_pin("ha-test", "h5py")]
