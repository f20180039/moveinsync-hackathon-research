"""Transport Manager configuration -- the shared base plus the knobs only
daily shift planning has."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..common.config import (ROOT, BaseConfig, env_float, env_int,  # noqa: F401
                             shared_env)


@dataclass(frozen=True)
class Config(BaseConfig):
    history_days: int          # how much history feeds the forecast
    target_date: str | None    # YYYY-MM-DD; None = day after the last trip
    peak_hours: int            # how many hours to name as peaks
    capacity_buffer_pct: float # spare vehicles on top of the forecast
    run_at: str                # HH:MM local, for the scheduler
    audience: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            **shared_env(),
            history_days=env_int("TRIGGER_HISTORY_DAYS", 28),
            target_date=os.environ.get("TRIGGER_TARGET_DATE", "").strip() or None,
            peak_hours=env_int("TRIGGER_PEAK_HOURS", 3),
            capacity_buffer_pct=env_float("TRIGGER_CAPACITY_BUFFER_PCT", 10.0),
            run_at=os.environ.get("TRIGGER_RUN_AT", "").strip() or "06:30",
            audience=os.environ.get("TRIGGER_AUDIENCE", "").strip() or "Transport Manager",
        )
