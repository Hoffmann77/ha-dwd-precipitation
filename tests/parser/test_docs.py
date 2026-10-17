"""What the README must tell users of older installs, from the release history."""

from __future__ import annotations

from pathlib import Path

from tests.entity_ids import RELEASED_2026_10_0_IDS, RENAMED_SINCE_2026_10_0

ROOT = Path(__file__).parents[2]


def test_readme_names_the_old_id_of_every_renamed_entity():
    """Installs from 2026.10.0 keep their ids; the README note must name them."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    note = readme.split("Installs set up before 2026.10.1 keep their entity ids", 1)[1]
    note = note.split("\n\n", 1)[0]
    missing = [
        RELEASED_2026_10_0_IDS[key]
        for key in RENAMED_SINCE_2026_10_0
        if f"_{RELEASED_2026_10_0_IDS[key]}`" not in note
    ]
    assert missing == []
