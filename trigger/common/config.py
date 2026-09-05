"""Configuration shared by every agent under `trigger/`.

Nothing here is hardcoded that belongs in `.env`: the Slack webhook, the
Sarvam key and the data directory are the repository's OWN existing
variables (SLACK_WEBHOOK_URL, SARVAM_API_KEY, SIGNALDESK_DATA), read by the
existing code we call into. The TRIGGER_* names are additive and every one
has a working default, so both agents run with an unchanged `.env`.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Repo root is three levels up: <root>/trigger/common/config.py.
ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE = ROOT / "service"
STATE_DIR = ROOT / "trigger" / ".state"

# `signaldesk` lives under service/. Importing it is reuse, not modification.
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def resolve_data_dir() -> str:
    """Honour the repository's own SIGNALDESK_DATA, but never die on it.

    `SIGNALDESK_DATA` is written relative to `service/` (the cwd the API is
    started from), so the same string is resolved against service/, then the
    repo root, then as given. If none of those exist -- the committed `.env`
    currently points at `../data/fixture`, which is not in the tree -- fall
    back to `data/sample`, which is. An agent that runs on the sample beats a
    crash on a path this package does not own.
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
class BaseConfig:
    """What both agents need: where the data is, what local clock to write
    in, and how to reach the model."""
    data_dir: str
    tz_offset_min: int         # local clock the output is written in (IST)
    model: str
    base_url: str              # OpenAI-compatible endpoint
    max_tokens: int
    temperature: float
    dry_run: bool              # build the message, do not post it


def shared_env() -> dict:
    """The BaseConfig fields, read from the environment once."""
    from signaldesk import model as _model      # existing model layer
    return {
        "data_dir": resolve_data_dir(),
        "tz_offset_min": env_int("TRIGGER_TZ_OFFSET_MIN", 330),
        "model": os.environ.get("TRIGGER_MODEL", "").strip() or _model.MODEL,
        # Defaults to the endpoint the existing model layer already uses;
        # overridable so a chain can be pointed at a local or proxied
        # OpenAI-compatible server without touching code.
        "base_url": os.environ.get("TRIGGER_BASE_URL", "").strip() or _model.BASE_URL,
        "max_tokens": env_int("TRIGGER_MAX_TOKENS", 16000),
        "temperature": env_float("TRIGGER_TEMPERATURE", 0.2),
        "dry_run": env_bool("TRIGGER_DRY_RUN", False),
    }
