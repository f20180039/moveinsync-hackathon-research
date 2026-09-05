"""The smallest thing that stops notification spam: a JSON file.

A ride that is still delayed on the next run must not produce the same
escalation again -- but a ride whose severity or delay materially CHANGED
must. So each escalation carries a fingerprint (issue type, severity, delay
rounded to a bucket) and this compares it to what was last reported:

    NEW      -- this ride has not been escalated before
    UPDATED  -- escalated before, but the fingerprint changed
    REPEAT   -- same situation as last time; suppressed by default

Deliberately not a database. One file, one dict, written atomically. Swapping
it for Redis later is one module, not a redesign.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("trigger")

NEW, UPDATED, REPEAT = "NEW", "UPDATED", "REPEAT"


class SeenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            self.data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.data = {}
        except (json.JSONDecodeError, OSError) as exc:
            # A corrupt state file must not stop the morning's escalations;
            # the worst case is one duplicate notification.
            logger.warning("state: unreadable (%s), starting empty", type(exc).__name__)
            self.data = {}

    def classify(self, key: str, fingerprint: str) -> str:
        prev = self.data.get(str(key))
        if prev is None:
            return NEW
        return REPEAT if prev.get("fingerprint") == fingerprint else UPDATED

    def record(self, key: str, fingerprint: str, extra: dict | None = None) -> None:
        entry = {"fingerprint": fingerprint, "at": int(time.time() * 1000)}
        if extra:
            entry.update(extra)
        self.data[str(key)] = entry

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(self.data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            logger.warning("state: could not persist (%s)", type(exc).__name__)
