"""ISO timestamps for state attributes and stored payloads. HA-free."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, overload


@overload
def iso(dt: datetime) -> str: ...
@overload
def iso(dt: None) -> None: ...
def iso(dt: datetime | None) -> str | None:
    """Serialize a timestamp for a state attribute or a restore payload."""
    return dt.isoformat() if dt is not None else None


def parse_utc(raw: Any) -> datetime | None:
    """Parse a stored ISO timestamp as an aware datetime; naive counts as UTC.

    Anything that is not a readable timestamp is None, so a damaged restore
    payload loses that one field rather than the whole entity.
    """
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
