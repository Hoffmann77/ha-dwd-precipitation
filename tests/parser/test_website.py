"""Every page of the documentation site exists in English and in German."""

from __future__ import annotations

import re
import unicodedata
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

HEADING = re.compile(r"^(#{2,6})\s+(.*?)\s*$")
EXPLICIT_ID = re.compile(r"\s*\{#([^}]+)\}$")


def _pages(folder: Path) -> set[str]:
    return {
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.suffix in (".md", ".mdx")
    }


def _headings(text: str) -> list[str]:
    """Return the text of every level-2+ heading outside code blocks."""
    headings, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := HEADING.match(line)):
            headings.append(match.group(2))
    return headings


def _slug(heading: str) -> str:
    """Return the anchor Docusaurus gives a heading (github-slugger's rules)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links: their text
    text = text.replace("`", "").replace("*", "").lower()
    return "".join(
        "-" if char == " " else char
        for char in text
        if char in " -_" or unicodedata.category(char)[0] in "LN"
    )


def _anchors(headings: list[str]) -> list[str]:
    """Return the anchors of a page's headings, numbering repeats like Docusaurus.

    A heading with an explicit id (``### Measured with {#dry-streak-source}``)
    has that id, which keeps an anchor stable when the heading changes.

    """
    seen: dict[str, int] = {}
    anchors = []
    for heading in headings:
        if match := EXPLICIT_ID.search(heading):
            anchors.append(match.group(1))
            continue
        slug = _slug(heading)
        anchors.append(f"{slug}-{seen[slug]}" if slug in seen else slug)
        seen[slug] = seen.get(slug, 0) + 1
    return anchors


@pytest.mark.parametrize("instance", INSTANCES)
def test_every_page_has_an_english_and_a_german_version(instance):
    en_dir, de_dir = INSTANCES[instance]
    en, de = _pages(en_dir), _pages(de_dir)
    assert en, f"no pages in {en_dir}"
    assert sorted(en - de) == [], f"missing German translation in {de_dir}"
    assert sorted(de - en) == [], f"German page without English source in {en_dir}"


def _page_pairs():
    for instance, (en_dir, de_dir) in INSTANCES.items():
        for page in sorted(_pages(en_dir) & _pages(de_dir)):
            yield pytest.param(en_dir / page, de_dir / page, id=f"{instance}/{page}")


@pytest.mark.parametrize(("en_page", "de_page"), list(_page_pairs()))
def test_german_headings_keep_the_english_anchors(en_page, de_page):
    """A German heading carries its English heading's id, so anchor links work in both."""
    expected = _anchors(_headings(en_page.read_text(encoding="utf-8")))
    actual = [
        match.group(1) if (match := EXPLICIT_ID.search(heading)) else None
        for heading in _headings(de_page.read_text(encoding="utf-8"))
    ]
    assert actual == expected
