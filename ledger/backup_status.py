"""Reads the small status file the optional backup service leaves behind.

The app never talks to cloud storage itself. A separate container does the
backup and writes ``status.json``; this module only reads that local file so
the History page can show when the last backup ran. Everything in the file is
treated as untrusted: wrong types or nonsense are ignored, never executed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAX_BYTES = 4096
STALE_AFTER = timedelta(hours=48)


@dataclass(frozen=True)
class BackupStatus:
    state: str                      # "ok", "stale", or "failed"
    last_success: datetime | None   # timezone-aware, UTC
    last_attempt: datetime | None
    snapshots: int
    message: str


def _when(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_status(path: str | None, now: datetime) -> BackupStatus | None:
    """None means the backup service has never run (or isn't set up)."""
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    success, attempt = _when(data.get("last_success")), _when(data.get("last_attempt"))
    if success is None and attempt is None:
        return None
    count = data.get("snapshots")
    count = count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count < 1_000_000 else 0
    message = data.get("message")
    message = " ".join(message.split())[:200] if isinstance(message, str) else ""
    if data.get("ok") is not True:
        state = "failed"
    elif success is None or now - success > STALE_AFTER:
        state = "stale"
    else:
        state = "ok"
    return BackupStatus(state, success, attempt, count, message)
