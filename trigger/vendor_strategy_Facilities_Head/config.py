"""Facilities Head configuration -- the shared base plus the knobs vendor
analysis needs. Every scoring weight is here, not buried in the code, because
a weight nobody can find is a weight nobody can defend."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..common.config import (ROOT, STATE_DIR, BaseConfig, env_bool,  # noqa: F401
                             env_float, env_int, shared_env)


@dataclass(frozen=True)
class Config(BaseConfig):
    date: str | None           # YYYY-MM-DD for daily; None = last day with data
    month: str | None          # YYYY-MM for monthly; None = last full month
    quarter: str | None        # "2026Q2" or None = last 3 months present
    min_trips: int             # below this a vendor is reported but not ranked
    min_trips_daily: int       # the same floor for a single day
    top_n: int                 # vendors named in a Slack report
    poor_day_ontime: float     # a day below this on-time % is a "poor day"
    w_service: float           # scorecard weights -- documented in scorecard.py
    w_reliability: float
    w_cost: float
    audience: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            **shared_env(),
            date=os.environ.get("VENDOR_DATE", "").strip() or None,
            month=os.environ.get("VENDOR_MONTH", "").strip() or None,
            quarter=os.environ.get("VENDOR_QUARTER", "").strip() or None,
            min_trips=env_int("VENDOR_MIN_TRIPS", 9),
            min_trips_daily=env_int("VENDOR_MIN_TRIPS_DAILY", 3),
            top_n=env_int("VENDOR_TOP_N", 5),
            poor_day_ontime=env_float("VENDOR_POOR_DAY_ONTIME", 80.0),
            w_service=env_float("VENDOR_W_SERVICE", 0.40),
            w_reliability=env_float("VENDOR_W_RELIABILITY", 0.30),
            w_cost=env_float("VENDOR_W_COST", 0.30),
            audience=os.environ.get("VENDOR_AUDIENCE", "").strip() or "Facilities Head",
        )
