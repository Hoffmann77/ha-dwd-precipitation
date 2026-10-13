"""What the docs state that the code or the release history pins down."""

from __future__ import annotations

import re
from pathlib import Path

from tests.entity_ids import RELEASED_2026_10_0_IDS, RENAMED_SINCE_2026_10_0

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


def test_adr_references_resolve():
    """Every "ADR NNNN" CLAUDE.md cites exists, and the index lists every record."""
    adr = ROOT / "docs" / "adr"
    records = {p.name[:4]: p.name for p in adr.glob("[0-9][0-9][0-9][0-9]-*.md")}
    cited = set(re.findall(r"ADR (\d{4})", (ROOT / "CLAUDE.md").read_text(encoding="utf-8")))
    assert sorted(cited - records.keys()) == [], "CLAUDE.md cites records that do not exist"
    index = (adr / "README.md").read_text(encoding="utf-8")
    assert sorted(n for n in records.values() if f"({n})" not in index) == []
