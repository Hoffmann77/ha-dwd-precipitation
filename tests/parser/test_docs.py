"""What the docs must tell users of older installs, from the release history."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.entity_ids import RELEASED_2026_10_0_IDS, RENAMED_SINCE_2026_10_0

ROOT = Path(__file__).parents[2]

# The Upgrading page of the docs site, in English and German.
UPGRADING = {
    "en": ROOT / "website/docs/help/upgrading.md",
    "de": ROOT / "website/i18n/de/docusaurus-plugin-content-docs/current/help/upgrading.md",
}


@pytest.mark.parametrize("locale", UPGRADING)
def test_upgrading_names_the_old_and_new_id_of_every_renamed_entity(locale):
    """Installs from before 2026.11.0 keep their ids; the Upgrading page must map them."""
    page = UPGRADING[locale].read_text(encoding="utf-8")
    missing = [
        entity_id
        for key, new_id in RENAMED_SINCE_2026_10_0.items()
        for entity_id in (RELEASED_2026_10_0_IDS[key], new_id)
        if f"_{entity_id}`" not in page
    ]
    assert missing == []
