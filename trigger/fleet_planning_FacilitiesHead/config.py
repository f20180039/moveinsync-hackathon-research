"""Fleet-planning configuration -- the shared base plus the knobs only a
NEXT-WEEK fleet projection has.

capacity_buffer_pct is deliberately the SAME environment variable the daily
shift planner reads (TRIGGER_CAPACITY_BUFFER_PCT). There is one standby policy
in this system, not one per agent: a fleet plan that budgeted a different
buffer from the roster it feeds would be two answers to one question.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..common.config import (ROOT, BaseConfig, env_float, env_int,  # noqa: F401
                             shared_env)


@dataclass(frozen=True)
class Config(BaseConfig):
    capacity_buffer_pct: float   # spare vehicles on top of the projection
    days_ahead: int              # how many days of next week to project
    run_at: str                  # HH:MM local, for a scheduler
    audience: str
    # Below this many basis days a band's projection is reported but flagged.
    # Not a second threshold: forecast.MIN_BASIS_DAYS_BY_METRIC already decides
    # what is projectable at all; this only decides what gets called out in
    # the message as thin evidence.
    thin_basis_days: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            **shared_env(),
            capacity_buffer_pct=env_float("TRIGGER_CAPACITY_BUFFER_PCT", 10.0),
            days_ahead=env_int("TRIGGER_FLEET_DAYS_AHEAD", 7),
            run_at=os.environ.get("TRIGGER_FLEET_RUN_AT", "").strip() or "07:00",
            audience=os.environ.get("TRIGGER_FLEET_AUDIENCE", "").strip()
                     or "Facilities Head",
            thin_basis_days=env_int("TRIGGER_FLEET_THIN_BASIS_DAYS", 3),
        )
