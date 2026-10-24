"""ISO timestamps for state attributes and stored payloads. HA-free."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, overload


@overload
def iso(dt: datetime) -> str: ...
@overload
def iso(dt: None) -> None: ...
def iso(dt: datetime | None) -> str | None:
    """Serialize a timestamp for a state attribute or a restore payload.

    Returns the ISO 8601 string of an aware datetime, for example
    "2026-10-17T12:05:00+00:00", which Home Assistant can store and show as it
    is. None stays None, so an optional timestamp (a window end the file did
    not state, say) can be passed straight through without a check at every
    caller.

    """
    return dt.isoformat() if dt is not None else None


def parse_utc(raw: Any) -> datetime | None:
    """Parse a stored ISO timestamp as an aware datetime; naive counts as UTC.

    The counterpart of iso(), used when restoring data Home Assistant kept
    across a restart. A timestamp without a time zone is taken as UTC, because
    that is what the integration always wrote. Anything that is not a readable
    timestamp string (missing, damaged, another type) gives None, so a damaged
    restore payload loses that one field rather than the whole entity.

    """
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
