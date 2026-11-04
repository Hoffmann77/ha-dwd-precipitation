"""The English and German translations must define the same keys."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.parser.test_website import INSTANCES, _anchors, _headings

ROOT = Path(__file__).parents[2]
COMPONENT = ROOT / "custom_components/dwd_precipitation"
TRANSLATIONS = COMPONENT / "translations"

# A link into the documentation site, as the options form writes it: the
# {docs_url} placeholder, then the page (German ones under /de) and an anchor.
DOCS_LINK = re.compile(r"\]\(\{docs_url\}(/de)?/([^)#]+)(?:#([^)]+))?\)")


def _keys(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _keys(value, f"{prefix}.{key}")
    else:
        yield prefix


def _strings(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{prefix}.{key}")
    else:
        yield prefix, node


def _load(lang: str) -> dict:
    return json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))


def test_en_and_de_define_the_same_keys():
    en = set(_keys(_load("en")))
    de = set(_keys(_load("de")))
    assert en - de == set(), "missing in de.json"
    assert de - en == set(), "missing in en.json"


def test_the_docs_url_is_the_manifests():
    # const.py imports Home Assistant, which this tier does not have: read it.
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    (docs_url,) = re.findall(r'^DOCS_URL = "([^"]+)"$', const, re.MULTILINE)
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["documentation"] == f"{docs_url}/"


def _links(lang: str) -> dict[str, list[tuple[str, str | None]]]:
    """Return every string's docs links, as (page, anchor), by key."""
    links = {}
    for key, text in _strings(_load(lang)):
        found = DOCS_LINK.findall(text)
        if found:
            assert all(bool(de) == (lang == "de") for de, _, _ in found), key
            links[key] = [(page, anchor or None) for _, page, anchor in found]
    return links


def test_en_and_de_link_the_same_docs():
    """A German string links the German page of what its English one links."""
    assert _links("en")
    assert _links("de") == _links("en")


@pytest.mark.parametrize("lang", ["en", "de"])
def test_every_docs_link_finds_its_page_and_anchor(lang):
    """The options form's links point at a page and heading the site has."""
    folder = INSTANCES["docs"][0 if lang == "en" else 1]
    for key, links in _links(lang).items():
        for page, anchor in links:
            candidates = [folder / f"{page}{suffix}" for suffix in (".md", ".mdx")]
            path = next((p for p in candidates if p.exists()), None)
            assert path is not None, f"{key}: no page {page}"
            if anchor:
                assert anchor in _anchors(_headings(path.read_text(encoding="utf-8"))), (
                    f"{key}: no #{anchor} on {page}"
                )
