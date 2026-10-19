"""Every page of the documentation site exists in English and in German."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
I18N_DE = ROOT / "website/i18n/de"

# Each docs instance of website/docusaurus.config.js: its English sources and
# the folder Docusaurus reads its German translation from.
INSTANCES = {
    "docs": (ROOT / "website/docs", I18N_DE / "docusaurus-plugin-content-docs/current"),
    "development": (
        ROOT / "website/development",
        I18N_DE / "docusaurus-plugin-content-docs-development/current",
    ),
    "adr": (ROOT / "docs/adr", I18N_DE / "docusaurus-plugin-content-docs-adr/current"),
}


def _pages(folder: Path) -> set[str]:
    return {
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.suffix in (".md", ".mdx")
    }


@pytest.mark.parametrize("instance", INSTANCES)
def test_every_page_has_an_english_and_a_german_version(instance):
    en_dir, de_dir = INSTANCES[instance]
    en, de = _pages(en_dir), _pages(de_dir)
    assert en, f"no pages in {en_dir}"
    assert sorted(en - de) == [], f"missing German translation in {de_dir}"
    assert sorted(de - en) == [], f"German page without English source in {en_dir}"
