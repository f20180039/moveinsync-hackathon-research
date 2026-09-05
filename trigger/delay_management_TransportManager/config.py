"""Team Manager configuration -- the shared base plus the escalation
thresholds. Every threshold is an env var with a working default, so tuning
the agent on the day needs no code change."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..common.config import (ROOT, STATE_DIR, BaseConfig, env_bool,  # noqa: F401
                             env_int, shared_env)


@dataclass(frozen=True)
class Config(BaseConfig):
    now: str | None            # "YYYY-MM-DD HH:MM" local; None = auto-detect
    lookahead_min: int         # rides starting within this window count as upcoming
    lookback_min: int          # rides that ended this recently still count
    eta_deviation_min: int     # minutes of arrival slip that is an escalation
    driver_late_min: int       # minutes of start slip that is a driver delay
    pickup_slip_min: int       # minutes an employee pickup may slip
    noshow_legs_min: int       # no-show riders on one trip before it matters
    max_escalations: int       # cap on rides sent to the model in one run
    send_repeats: bool         # re-notify an unchanged escalation
    state_path: str
    audience: str

    @classmethod
    def from_env(cls) -> "Config":
        from signaldesk import constants as C
        return cls(
            **shared_env(),
            now=os.environ.get("TEAM_NOW", "").strip() or None,
            lookahead_min=env_int("TEAM_LOOKAHEAD_MIN", 45),
            lookback_min=env_int("TEAM_LOOKBACK_MIN", 60),
            # The repo already defines what a breach of arrival is worth:
            # constants.SLA_BREACH_MS (15 minutes). Reused as the default
            # rather than inventing a second number.
            eta_deviation_min=env_int("TEAM_ETA_DEVIATION_MIN",
                                      C.SLA_BREACH_MS // 60_000),
            driver_late_min=env_int("TEAM_DRIVER_LATE_MIN", 10),
            pickup_slip_min=env_int("TEAM_PICKUP_SLIP_MIN", 10),
            noshow_legs_min=env_int("TEAM_NOSHOW_LEGS_MIN", 2),
            max_escalations=env_int("TEAM_MAX_ESCALATIONS", 8),
            send_repeats=env_bool("TEAM_SEND_REPEATS", False),
            state_path=os.environ.get("TEAM_STATE_PATH", "").strip()
                       or str(STATE_DIR / "delay_management_TransportManager_seen.json"),
            audience=os.environ.get("TEAM_AUDIENCE", "").strip() or "Team Manager",
        )
