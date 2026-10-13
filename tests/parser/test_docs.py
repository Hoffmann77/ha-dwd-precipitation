"""CLAUDE.md's architecture block lists every module, and only those."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
COMPONENT = ROOT / "custom_components" / "dwd_precipitation"


def _architecture_entries() -> set[str]:
    """Return the module paths the Architecture code block names."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    block = text.split("## Architecture", 1)[1].split("```")[1]
    entries: set[str] = set()
    package = ""
    for line in block.splitlines():
        if match := re.match(r"^(\S+)(?:\s|$)", line):
            name = match[1]
            package = name if name.endswith("/") else ""
            if not name.endswith("/"):
                entries.add(name)
        elif package and (match := re.match(r"^  (\S+\.py)\b", line)):
            entries.add(package + match[1])
    return entries


def test_architecture_lists_every_module():
    on_disk = {p.relative_to(COMPONENT).as_posix() for p in COMPONENT.rglob("*.py")}
    listed = _architecture_entries()
    assert sorted(on_disk - listed) == [], "modules CLAUDE.md does not describe"
    assert sorted(listed - on_disk) == [], "CLAUDE.md describes modules that are gone"
