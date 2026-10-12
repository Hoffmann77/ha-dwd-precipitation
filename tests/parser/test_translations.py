"""The English and German translations must define the same keys."""

from __future__ import annotations

import json
from pathlib import Path

TRANSLATIONS = Path(__file__).parents[2] / "custom_components/dwd_precipitation/translations"


def _keys(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _keys(value, f"{prefix}.{key}")
    else:
        yield prefix


def test_en_and_de_define_the_same_keys():
    en = set(_keys(json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))))
    de = set(_keys(json.loads((TRANSLATIONS / "de.json").read_text(encoding="utf-8"))))
    assert en - de == set(), "missing in de.json"
    assert de - en == set(), "missing in en.json"
