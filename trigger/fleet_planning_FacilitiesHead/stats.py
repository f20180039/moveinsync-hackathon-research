"""Next week's demand, projected per day and shift band, turned into a fleet
recommendation.

THE CHAIN, end to end, all of it in Python:
    measure demand   registry.riders_per_day (planned headcount per day)
    project it       forecast.project -- the seasonal baseline, same weekday
                     four weeks back, recency-weighted 4/3/2/1
    compare capacity registry.avg_cab_capacity -- seats per vehicle actually
                     run in that band
    name the delta   vehicles needed vs vehicles the same band ran last week

NOTHING HERE IS A SECOND ALLOCATOR. The vehicle arithmetic is the daily shift
planner's own, lifted into `vehicles_for` below and used by both: a count is
`round(riders / seats_per_vehicle)`, a standby buffer of
TRIGGER_CAPACITY_BUFFER_PCT sits on top, and drivers track buffered vehicles
one-for-one (there is no separate driver roster feed in this dataset -- the
shift planner's own note). Same env var, same formula, so a fleet plan and the
roster it feeds cannot disagree about what a buffer is.

WHY IT IS TWO-SIDED. This is the whole point of the demand metric being
two-sided in the first place. A band projected ABOVE the vehicles it ran gets
an ADD recommendation -- fall short and employees are stranded, which is a
service and safety failure. A band projected BELOW gets a RELEASE
recommendation -- overbook and the company pays for empty seats. Both are
reported, in one table, with the direction named. An agent that only reported
one side would answer half the question the request asked.

WHAT TRAVELS WITH EVERY NUMBER. A manager preparing next week has to know how
much history the figure rests on, so each row carries the projection's
interval, its basis-day count, and any basis day the anomaly screen threw out
(a festive or extended-weekend day that would otherwise have dragged the
projection down and UNDER-booked the fleet). A number without that context is
a guess wearing a suit.

The model never computes any of this -- it is handed the finished table and
asked for prose. See chain.py.
"""
from __future__ import annotations

import datetime as dt
import math

import duckdb

from ..common import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from ..common import run_context
from signaldesk import forecast, ingest, registry
from signaldesk.schemas import Dimension, Slice, Window

DAY_MS = 86_400_000
DEMAND_METRIC = "riders_per_day"


def _date_label(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def _weekday(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%A")


def load(data_dir: str) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """The repository's own tolerant loader, exactly as every other agent
    uses it. No second ingest."""
    con = duckdb.connect()
    health = ingest.load_all(con, ingest.source_for(data_dir))
    return con, {feed: {"rows": h.rows_loaded, "confidence": round(h.confidence, 2)}
                 for feed, h in health.items()}


def week_start(con, run=None) -> int:
    """The first day of the week being planned.

    Reconciled with the sweep when a run context is available (the day after
    the run's own window), self-derived from the data otherwise -- the same
    rule, and the same reasoning, as shift_planning's target_window.
    """
    if run is not None and run.reconciled and run.window_end_ms is not None:
        anchor = run.window_end_ms - 1
    else:
        anchor = ingest.latest_scheduled_ms(con)
    return (anchor // DAY_MS + 1) * DAY_MS


# ---------------------------------------------------------------------------
# The vehicle arithmetic. ONE implementation, shared with the shift planner's
# own convention -- see the module docstring.
# ---------------------------------------------------------------------------

def vehicles_for(riders: float, seats_per_vehicle: float | None,
                 buffer_pct: float) -> dict:
    """riders -> vehicles required, with buffer, and drivers.

    `seats_per_vehicle` is None when no usable capacity was recorded for that
    band: the answer is then None rather than a made-up fleet size, and the
    caller says so. A zero or negative capacity is the same case -- a
    zero-seat cab is a missing field, not a vehicle with no seats.
    """
    if not seats_per_vehicle or seats_per_vehicle <= 0 or riders is None:
        return {"vehicles": None, "vehiclesWithBuffer": None, "drivers": None,
                "seatsPerVehicle": None}
    buffer = 1.0 + buffer_pct / 100.0
    vehicles = max(1, math.ceil(riders / seats_per_vehicle))
    buffered = max(1, math.ceil(riders / seats_per_vehicle * buffer))
    return {
        "vehicles": vehicles,
        "vehiclesWithBuffer": buffered,
        # One driver per buffered vehicle: this dataset carries no separate
        # driver roster, the same reasoning the daily planner records.
        "drivers": buffered,
        "seatsPerVehicle": round(seats_per_vehicle, 2),
    }


def _projection_row(con, slc: Slice, target_ms: int, cfg, metric) -> dict:
    """One band on one day: the projection, its evidence, and the fleet it
    implies."""
    p = forecast.project(con, metric, slc, target_ms)
    screened = [{"date": b.date, "value": b.value, "reason": b.anomaly}
                for b in p.basis if b.excluded]
    flagged = [{"date": b.date, "value": b.value, "reason": b.anomaly}
               for b in p.basis if b.anomaly and not b.excluded]

    # Seats per vehicle for THIS band, measured over the week before the
    # target -- the same slice the demand is projected for, so a BUS band is
    # not sized with a CAB band's seat count.
    ref_window = Window(target_ms - 7 * DAY_MS, target_ms)
    seats = registry.avg_cab_capacity(con, slc, ref_window)
    fleet = vehicles_for(p.projected, seats, cfg.capacity_buffer_pct)

    # WHAT WE COMPARE AGAINST: the SAME WEEKDAY one week earlier -- last
    # Tuesday for next Tuesday -- not the reference week's daily average.
    #
    # This is the same weekday-seasonality trap forecast._same_weekday_reference
    # exists for, and it bites harder here because the output is an
    # instruction. MEASURED on data/real: Wednesday runs 25,570 riders/day and
    # Saturday 1,759, so comparing a Saturday projection against a weekly
    # average produced "RELEASE 20 vehicles" on every Saturday and "ADD" on
    # every weekday -- pure calendar, zero signal, and a manager who followed
    # it would strand people on Monday. A single matching weekday is also the
    # number a manager can actually check ("what did we run last Saturday?").
    last_same_weekday = Window(target_ms - 7 * DAY_MS, target_ms - 6 * DAY_MS)
    ran_riders, _n = registry.evaluate_with_n(con, metric, slc, last_same_weekday)
    ran = vehicles_for(ran_riders, seats, cfg.capacity_buffer_pct)

    delta = None
    if fleet["vehiclesWithBuffer"] is None or ran["vehiclesWithBuffer"] is None:
        # Not "no change needed" -- NOT KNOWN. Reporting an unprojectable band
        # as HOLD would read as a decision that was never made.
        direction = "NO_PROJECTION"
    else:
        delta = fleet["vehiclesWithBuffer"] - ran["vehiclesWithBuffer"]
        # Two-sided by construction: a surplus and a shortfall are different
        # recommendations, not two signs of one.
        direction = "ADD" if delta > 0 else ("RELEASE" if delta < 0 else "HOLD")

    return {
        "date": _date_label(target_ms),
        "weekday": _weekday(target_ms),
        "band": slc.value or "ALL",
        "projectedRiders": None if p.projected is None else round(p.projected, 1),
        "intervalLow": None if p.interval_low is None else round(p.interval_low, 1),
        "intervalHigh": None if p.interval_high is None else round(p.interval_high, 1),
        "basisDaysUsed": p.basis_days_used,
        "basisDaysWanted": forecast.BASIS_WEEKS,
        "thinEvidence": p.basis_days_used < cfg.thin_basis_days,
        "withheld": p.withheld,
        "degraded": p.degraded,
        "readiness": p.readiness,
        "screenedBasisDays": screened,
        "flaggedBasisDays": flagged,
        "seatsPerVehicle": fleet["seatsPerVehicle"],
        "vehiclesRequired": fleet["vehicles"],
        "vehiclesWithBuffer": fleet["vehiclesWithBuffer"],
        "driversRequired": fleet["drivers"],
        "ranRiders": None if ran_riders is None else round(ran_riders, 1),
        "ranDate": _date_label(target_ms - 7 * DAY_MS),
        "ranVehiclesWithBuffer": ran["vehiclesWithBuffer"],
        "vehicleDelta": delta,
        "direction": direction,
        "note": p.note,
        # Every projected figure carries the queries that produced it, the
        # same "paste it and get the same number" contract every metric has.
        "basisSql": [b.sql for b in p.basis],
    }


def build(cfg, run=None) -> dict:
    """Next week's demand and fleet, as one JSON-serialisable dict."""
    con, health = load(cfg.data_dir)
    try:
        metric = registry.by_id(DEMAND_METRIC)
        start = week_start(con, run)
        ref_window = Window(start - 7 * DAY_MS, start)
        bands = registry.distinct_values(con, Dimension.SHIFT, ref_window)

        days = []
        for i in range(cfg.days_ahead):
            target = start + i * DAY_MS
            overall = _projection_row(con, Slice.all(), target, cfg, metric)
            rows = [_projection_row(con, Slice(Dimension.SHIFT, b), target, cfg, metric)
                    for b in bands]
            days.append({
                "date": _date_label(target),
                "weekday": _weekday(target),
                "overall": overall,
                "byBand": rows,
            })

        # The week's own totals, summed from the per-day overall rows rather
        # than projected separately -- one method, so the total and the days
        # cannot disagree.
        projected_days = [d["overall"] for d in days
                          if d["overall"]["projectedRiders"] is not None]
        week_riders = sum(d["projectedRiders"] for d in projected_days)
        adds = [r for d in days for r in d["byBand"] if r["direction"] == "ADD"]
        releases = [r for d in days for r in d["byBand"] if r["direction"] == "RELEASE"]

        return {
            "weekStart": _date_label(start),
            "weekEnd": _date_label(start + (cfg.days_ahead - 1) * DAY_MS),
            "weekStartMs": start,
            "daysAhead": cfg.days_ahead,
            "bufferPct": cfg.capacity_buffer_pct,
            "metric": DEMAND_METRIC,
            "method": forecast.METHOD,
            "referenceWindowLabel": ref_window.label,
            "bands": bands,
            "days": days,
            "feedHealth": health,
            "totals": {
                "projectedRiders": round(week_riders, 1),
                "daysProjected": len(projected_days),
                "daysWithheld": sum(1 for d in days if d["overall"]["withheld"]),
                "addRecommendations": len(adds),
                "releaseRecommendations": len(releases),
                "vehiclesToAdd": sum(r["vehicleDelta"] for r in adds),
                "vehiclesToRelease": -sum(r["vehicleDelta"] for r in releases),
                "screenedBasisDays": sorted({s["date"] for d in days
                                             for r in [d["overall"]] + d["byBand"]
                                             for s in r["screenedBasisDays"]}),
            },
            "run": (run.as_json() if run is not None else None),
            "provenance": (run.provenance_line() if run is not None else None),
        }
    finally:
        con.close()
