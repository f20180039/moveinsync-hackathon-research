"""Deterministic vendor metrics. Every number in every report is computed here.

Nothing in this file interprets anything. It answers only "what happened",
in SQL and arithmetic, for one time window at a time -- so the daily,
monthly and quarterly triggers all measure a vendor the same way and a
figure can be traced to a column.

WHAT THE DATA SUPPORTS, and what it does not:

  supported   trips, on-time (MoveInSync's own delay_minutes), SLA adherence,
              average/p90/max delay, delay reasons, driver and cab
              non-compliance, riders planned vs actual, no-shows, dashboard
              cancellations, alerts (count and severity), rider ratings,
              vendor cost (bill.trip_cost, joined on trip_id), distance
  NOT in the  contracted SLA targets, contract terms, penalty clauses,
  dataset     complaint tickets, vendor capacity/fleet size, quoted rates
              per contract, reasons for escalation beyond event_type

Anything in the second list is reported as unavailable rather than
estimated. `coverage` on every metric block says how much of the window
actually carried the data behind it.
"""
from __future__ import annotations

import logging
import statistics

from ..common import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from signaldesk import constants as C

logger = logging.getLogger("trigger")

ON_TIME = f"coalesce(delay_minutes, 0) <= {C.ON_TIME_GRACE_MIN}"
SLA_OK = f"coalesce(delay_minutes, 0) <= {C.SLA_BREACH_MS // 60_000}"


def _pct(num, den, digits=1):
    if not den:
        return None
    return round(100.0 * (num or 0) / den, digits)


def _r(v, digits=2):
    return None if v is None else round(float(v), digits)


def _rows(con, sql):
    return con.sql(sql).fetchall()


def vendor_metrics(con, window, cfg) -> list[dict]:
    """One dict per vendor active in `window`, richest-evidence first.

    The cost join is LEFT: a vendor whose trips carry no bill line still gets
    every operational metric, and its cost fields come back None rather than
    zero -- a zero would read as "free", which is a lie.
    """
    sql = f"""
        WITH t AS (
            SELECT * FROM trips
            WHERE scheduled_at >= {window.start_ms} AND scheduled_at < {window.end_ms}
              AND vendor_id IS NOT NULL
        ), cost AS (
            SELECT trip_id, sum(trip_cost) AS trip_cost, sum(total_trip_km) AS billed_km
            FROM bill GROUP BY 1
        ), alert AS (
            SELECT trip_id, count(*) AS alerts,
                   sum(CASE WHEN severity IN ('Sev-1','Sev-2') THEN 1 ELSE 0 END) AS sev12
            FROM alerts GROUP BY 1
        ), rating AS (
            SELECT trip_id, avg(route_rating) AS route, avg(driver_rating) AS driver,
                   avg(safety_rating) AS safety, count(*) AS responses
            FROM feedback GROUP BY 1
        ), legs AS (
            SELECT trip_id,
                   sum(CASE WHEN not_boarding_reason = 'TRIP_CANCELLED_FROM_DASHBOARD'
                            THEN 1 ELSE 0 END) AS cancelled_legs,
                   sum(CASE WHEN not_boarding_reason = 'NO_SHOW' THEN 1 ELSE 0 END) AS noshow_legs
            FROM emp_legs GROUP BY 1
        )
        SELECT t.vendor_id,
               count(*)                                              AS trips,
               sum(CASE WHEN t.actual_at IS NOT NULL THEN 1 ELSE 0 END) AS completed,
               sum(CASE WHEN {ON_TIME} THEN 1 ELSE 0 END)            AS on_time,
               sum(CASE WHEN {SLA_OK} THEN 1 ELSE 0 END)             AS sla_ok,
               avg(coalesce(t.delay_minutes, 0))                     AS avg_delay,
               quantile_cont(coalesce(t.delay_minutes, 0), 0.9)      AS p90_delay,
               max(coalesce(t.delay_minutes, 0))                     AS max_delay,
               sum(CASE WHEN coalesce(t.delay_reason,'NODELAY') <> 'NODELAY'
                        THEN 1 ELSE 0 END)                           AS delayed,
               sum(CASE WHEN t.delay_reason = 'DRIVER' THEN 1 ELSE 0 END) AS driver_delays,
               sum(CASE WHEN t.is_driver_nc THEN 1 ELSE 0 END)       AS driver_nc,
               sum(CASE WHEN t.is_cab_nc THEN 1 ELSE 0 END)          AS cab_nc,
               sum(coalesce(t.plannedemployee_cnt, 0))               AS planned_riders,
               sum(coalesce(t.actualemployee_cnt, 0))                AS actual_riders,
               sum(coalesce(t.noshow_cnt, 0))                        AS noshows,
               avg(CASE WHEN t.actual_cab_capacity > 0
                        THEN t.actualemployee_cnt * 1.0 / t.actual_cab_capacity END) AS occupancy,
               sum(coalesce(l.cancelled_legs, 0))                    AS cancelled_legs,
               sum(coalesce(a.alerts, 0))                            AS alerts,
               sum(coalesce(a.sev12, 0))                             AS sev12,
               avg(r.route)                                          AS route_rating,
               avg(r.driver)                                         AS driver_rating,
               avg(r.safety)                                         AS safety_rating,
               sum(coalesce(r.responses, 0))                         AS rating_responses,
               sum(c.trip_cost)                                      AS cost,
               count(c.trip_cost)                                    AS costed_trips,
               sum(CASE WHEN c.trip_cost IS NOT NULL AND {ON_TIME}
                        THEN c.trip_cost END)                        AS cost_on_time,
               sum(CASE WHEN c.trip_cost IS NOT NULL AND NOT ({SLA_OK})
                        THEN c.trip_cost END)                        AS cost_breached,
               sum(t.traveled_km)                                    AS km,
               count(DISTINCT strftime(to_timestamp(
                     (t.scheduled_at + {cfg.tz_offset_min * 60_000}) / 1000),
                     '%Y-%m-%d'))                                    AS active_days
        FROM t
        LEFT JOIN cost   c ON c.trip_id = t.trip_id
        LEFT JOIN alert  a ON a.trip_id = t.trip_id
        LEFT JOIN rating r ON r.trip_id = t.trip_id
        LEFT JOIN legs   l ON l.trip_id = t.trip_id
        GROUP BY 1 ORDER BY 2 DESC
    """
    daily = _daily_series(con, window, cfg)
    out = []
    for row in _rows(con, sql):
        try:
            out.append(_shape(row, daily, cfg))
        except Exception as exc:
            logger.warning("metrics: skipped a vendor row (%s)", type(exc).__name__)
    return out


def _daily_series(con, window, cfg) -> dict[str, list[dict]]:
    """Per-vendor per-day on-time, for consistency and poor-day counts. This
    is what separates "averaged 90%" from "90% every day"."""
    off = cfg.tz_offset_min * 60_000
    sql = f"""
        SELECT vendor_id,
               strftime(to_timestamp((scheduled_at + {off}) / 1000), '%Y-%m-%d') AS d,
               count(*) AS trips,
               sum(CASE WHEN {ON_TIME} THEN 1 ELSE 0 END) AS on_time
        FROM trips
        WHERE scheduled_at >= {window.start_ms} AND scheduled_at < {window.end_ms}
          AND vendor_id IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
    """
    series: dict[str, list[dict]] = {}
    for vendor, day, trips, on_time in _rows(con, sql):
        series.setdefault(vendor, []).append(
            {"date": day, "trips": int(trips), "onTimePct": _pct(on_time, trips)})
    return series


def _shape(row, daily, cfg) -> dict:
    (vendor, trips, completed, on_time, sla_ok, avg_delay, p90, max_delay, delayed,
     driver_delays, driver_nc, cab_nc, planned_riders, actual_riders, noshows,
     occupancy, cancelled_legs, alerts, sev12, route_rating, driver_rating,
     safety_rating, rating_responses, cost, costed_trips, cost_on_time,
     cost_breached, km, active_days) = row

    days = daily.get(vendor, [])
    # Consistency is measured on days that actually carried enough trips for a
    # rate to mean anything -- one trip at 0% is not a bad day, it is one trip.
    rated_days = [d["onTimePct"] for d in days if d["trips"] >= 3 and d["onTimePct"] is not None]
    volatility = round(statistics.pstdev(rated_days), 1) if len(rated_days) >= 2 else None
    poor_days = sum(1 for p in rated_days if p < cfg.poor_day_ontime)

    cost = float(cost) if cost is not None else None
    cost_coverage = _pct(costed_trips, trips)
    cost_per_trip = _r(cost / trips) if cost is not None and trips else None
    # "Successful" = on time, by the repo's own definition. A vendor that
    # delivers 100 rides of which 60 are on time is paying for 100 and
    # delivering 60 -- cost per SUCCESSFUL ride is the figure that shows it.
    cost_per_on_time = _r(cost / on_time) if cost is not None and on_time else None
    cost_per_km = _r(cost / float(km)) if cost is not None and km else None

    return {
        "vendor": vendor,
        "trips": int(trips),
        "activeDays": int(active_days or 0),
        "completed": int(completed or 0),
        "completionPct": _pct(completed, trips),
        "onTime": int(on_time or 0),
        "onTimePct": _pct(on_time, trips),
        "slaAdherencePct": _pct(sla_ok, trips),
        "avgDelayMin": _r(avg_delay, 1),
        "p90DelayMin": _r(p90, 1),
        "maxDelayMin": _r(max_delay, 1),
        "delayedTripPct": _pct(delayed, trips),
        "driverAttributedDelays": int(driver_delays or 0),
        "driverNonCompliance": int(driver_nc or 0),
        "cabNonCompliance": int(cab_nc or 0),
        "plannedRiders": int(planned_riders or 0),
        "actualRiders": int(actual_riders or 0),
        "noShowRiders": int(noshows or 0),
        "noShowPct": _pct(noshows, planned_riders),
        "cancelledBookings": int(cancelled_legs or 0),
        "avgOccupancy": _r(occupancy),
        "alerts": int(alerts or 0),
        "alertsPer100Trips": _r((alerts or 0) * 100.0 / trips, 1) if trips else None,
        "severeAlerts": int(sev12 or 0),
        "routeRating": _r(route_rating),
        "driverRating": _r(driver_rating),
        "safetyRating": _r(safety_rating),
        "ratingResponses": int(rating_responses or 0),
        "totalCost": _r(cost, 0),
        "costCoveragePct": cost_coverage,
        "costPerTrip": cost_per_trip,
        "costPerOnTimeTrip": cost_per_on_time,
        "costPerKm": cost_per_km,
        "costOnBreachedTrips": _r(float(cost_breached), 0) if cost_breached is not None else None,
        "km": _r(float(km), 0) if km is not None else None,
        "onTimeByDay": days,
        "onTimeVolatility": volatility,
        "poorDays": poor_days,
        "ratedDays": len(rated_days),
    }


def totals(vendors: list[dict]) -> dict:
    """The programme-level picture the reports open with."""
    trips = sum(v["trips"] for v in vendors)
    on_time = sum(v["onTime"] for v in vendors)
    cost = sum(v["totalCost"] or 0 for v in vendors) or None
    costed = [v for v in vendors if v["totalCost"] is not None]
    return {
        "vendors": len(vendors),
        "trips": trips,
        "onTimePct": _pct(on_time, trips),
        "totalCost": _r(cost, 0),
        "costCoveragePct": _pct(sum(v["trips"] for v in costed), trips),
        "alerts": sum(v["alerts"] for v in vendors),
        "severeAlerts": sum(v["severeAlerts"] for v in vendors),
        "noShowPct": _pct(sum(v["noShowRiders"] for v in vendors),
                          sum(v["plannedRiders"] for v in vendors)),
    }
