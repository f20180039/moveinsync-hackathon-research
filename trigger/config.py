"""Every knob this package reads, in one place, all from the environment.

Nothing here is hardcoded that belongs in `.env`: the Slack webhook, the
Sarvam key and the data directory are the repository's OWN existing
variables (SLACK_WEBHOOK_URL, SARVAM_API_KEY, SIGNALDESK_DATA) and are read
by the existing code we call into, not re-declared here. The TRIGGER_* names
below are additive and every one of them has a working default, so the job
runs with an unchanged `.env`.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Repo root is two levels up from this file: <root>/trigger/config.py.
ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "service"

# `signaldesk` lives under service/. Importing it is reuse, not modification.
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def resolve_data_dir() -> str:
    """Honour the repository's own SIGNALDESK_DATA, but never die on it.

    `SIGNALDESK_DATA` is written relative to `service/` (that is the cwd the
    API is started from), so the same string is resolved against service/,
    then the repo root, then as given. If none of those exist -- the
    committed `.env` currently points at `../data/fixture`, which is not in
    the tree -- fall back to `data/sample`, which is. A shift plan that runs
    on the sample beats a crash on a path this package does not own.
    """
    override = os.environ.get("TRIGGER_DATA", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    raw = os.environ.get("SIGNALDESK_DATA", "").strip()
    if raw:
        candidates += [SERVICE / raw, ROOT / raw, Path(raw)]
    candidates.append(ROOT / "data" / "sample")
    for c in candidates:
        try:
            if c.is_dir():
                return str(c.resolve())
        except OSError:
            continue
    return str((ROOT / "data" / "sample").resolve())


@dataclass(frozen=True)
class Config:
    data_dir: str
    history_days: int          # how much history feeds the forecast
    tz_offset_min: int         # local clock the plan is written in (IST)
    target_date: str | None    # YYYY-MM-DD; None = day after the last trip
    peak_hours: int            # how many hours to name as peaks
    capacity_buffer_pct: float # spare vehicles on top of the forecast
    model: str
    base_url: str              # OpenAI-compatible endpoint for the LLM
    max_tokens: int
    temperature: float
    dry_run: bool              # build the message, do not post it
    run_at: str                # HH:MM local, for the scheduler
    audience: str

    @classmethod
    def from_env(cls) -> "Config":
        from signaldesk import model as _model   # existing model layer
        return cls(
            data_dir=resolve_data_dir(),
            history_days=_int("TRIGGER_HISTORY_DAYS", 28),
            tz_offset_min=_int("TRIGGER_TZ_OFFSET_MIN", 330),
            target_date=os.environ.get("TRIGGER_TARGET_DATE", "").strip() or None,
            peak_hours=_int("TRIGGER_PEAK_HOURS", 3),
            capacity_buffer_pct=_float("TRIGGER_CAPACITY_BUFFER_PCT", 10.0),
            model=os.environ.get("TRIGGER_MODEL", "").strip() or _model.MODEL,
            # Defaults to the endpoint the existing model layer already uses;
            # overridable so the chain can be pointed at a local or proxied
            # OpenAI-compatible server without touching code.
            base_url=os.environ.get("TRIGGER_BASE_URL", "").strip() or _model.BASE_URL,
            max_tokens=_int("TRIGGER_MAX_TOKENS", 16000),
            temperature=_float("TRIGGER_TEMPERATURE", 0.2),
            dry_run=_bool("TRIGGER_DRY_RUN", False),
            run_at=os.environ.get("TRIGGER_RUN_AT", "").strip() or "06:30",
            audience=os.environ.get("TRIGGER_AUDIENCE", "").strip() or "Transport Manager",
        )
