"""Load the ride feeds and turn them into the handful of numbers a shift plan
actually needs.

Loading is NOT reimplemented here: `signaldesk.ingest.load_all` is the
repository's own tolerant DuckDB loader, and it is what normalises the three
different trip_id formats, converts epoch seconds to milliseconds and buckets
`shift_type` into EARLY/DAY/EVENING/NIGHT bands. This module only queries the
views it leaves behind.

Local time: every timestamp in the data is absolute epoch ms, and a shift
plan is written in local (IST) time, so the hour and date arithmetic below
shifts by `tz_offset_min` before bucketing -- the same reasoning as
`signaldesk.constants.IST_OFFSET_MS`, expressed as a config value so a
non-IST tenant needs no code change.

The dataset has no cancellation flag. "Failed" is therefore reported as the
concrete things it DOES carry -- no-shows, driver/cab non-compliance, a
delay_reason other than NODELAY, and riders who did not board -- rather than
inventing a cancellation rate that no column supports.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb

from . import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from signaldesk import constants as C
from signaldesk import ingest

DAY_MS = 86_400_000
HOUR_MS = 3_600_000

# on-time, exactly as the rest of the repo defines it (constants.py's own
# note: MoveInSync's delay_minutes, not an end-time gap we derive).
_ONTIME = f"coalesce(delay_minutes, 0) <= {C.ON_TIME_GRACE_MIN}"


def _local_expr(col: str, off_ms: int) -> str:
    return f"({col} + {off_ms})"


def _epoch_day_to_date(day: int) -> str:
    return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=int(day))).strftime("%Y-%m-%d")


def _rows(con, sql: str) -> list[tuple]:
    return con.sql(sql).fetchall()


def _pct(num: float, den: float) -> float | None:
    if not den:
        return None
    return round(100.0 * num / den, 1)


def _r(value, digits: int = 1):
    return None if value is None else round(float(value), digits)


def load(data_dir: str) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Load every feed through the existing ingest layer. Returns the
    connection and a per-feed health/confidence summary."""
    con = duckdb.connect()
    health = ingest.load_all(con, ingest.source_for(data_dir))
    summary = {
        feed: {
            "rows": h.rows_loaded,
            "confidence": round(h.confidence, 2),
            "rejected": h.rows_rejected,
            "unmatched": h.unmatched_keys,
            "nullCritical": h.null_critical_fields,
        }
        for feed, h in health.items()
    }
    return con, summary


def target_window(con, cfg) -> dict:
    """The day being planned for, and the history window behind it.

    Default target day is the day AFTER the last scheduled trip in the data
    -- the same replay convention `api.startup` uses, so a re-run of the same
    dataset always plans the same morning instead of drifting with wall
    clock. TRIGGER_TARGET_DATE overrides it.
    """
    off = cfg.tz_offset_min * 60_000
    latest = ingest.latest_scheduled_ms(con)
    if cfg.target_date:
        d = datetime.strptime(cfg.target_date, "%Y-%m-%d").date()
        target_day = (d - date(1970, 1, 1)).days
    else:
        target_day = (latest + off) // DAY_MS + 1
    start_ms = target_day * DAY_MS - off
    return {
        "targetDate": _epoch_day_to_date(target_day),
        "targetWeekday": datetime.strptime(_epoch_day_to_date(target_day), "%Y-%m-%d").strftime("%A"),
        "targetDayEpoch": int(target_day),
        "windowStartMs": int(start_ms - cfg.history_days * DAY_MS),
        "windowEndMs": int(start_ms),
        "historyDays": cfg.history_days,
        "dataLatestDate": _epoch_day_to_date((latest + off) // DAY_MS),
    }


def _daily(con, w, off) -> list[dict]:
    sql = f"""
        SELECT {_local_expr('scheduled_at', off)} // {DAY_MS} AS d,
               count(*) AS trips,
               coalesce(sum(plannedemployee_cnt), 0) AS planned_emp,
               coalesce(sum(actualemployee_cnt), 0)  AS actual_emp,
               coalesce(sum(noshow_cnt), 0)          AS noshows,
               avg(coalesce(delay_minutes, 0))       AS avg_delay,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
        GROUP BY 1 ORDER BY 1
    """
    out = []
    for d, trips, pemp, aemp, noshow, avg_delay, ontime in _rows(con, sql):
        iso = _epoch_day_to_date(d)
        out.append({
            "date": iso,
            "weekday": datetime.strptime(iso, "%Y-%m-%d").strftime("%A"),
            "trips": int(trips),
            "plannedEmployees": int(pemp),
            "actualEmployees": int(aemp),
            "noShows": int(noshow),
            "avgDelayMin": _r(avg_delay),
            "onTimePct": _pct(ontime, trips),
        })
    return out



def _by_hour(con, w, off, weekday: int | None = None) -> list[dict]:
    """Trips per local hour. `weekday` (0=Monday) restricts the profile to the
    days that actually look like the day being planned -- a Sunday's shape is
    not a Wednesday's, and the sample data's weekday/weekend split is 25:1."""
    extra = ""
    if weekday is not None:
        # epoch day 0 is a Thursday, hence the +3 to reach Monday=0.
        extra = (f"AND ((({_local_expr('scheduled_at', off)} // {DAY_MS}) + 3) % 7) "
                 f"= {weekday}")
    sql = f"""
        SELECT CAST(FLOOR(({_local_expr('scheduled_at', off)} % {DAY_MS}) / {HOUR_MS}.0) AS INTEGER) AS h,
               count(*) AS trips,
               coalesce(sum(plannedemployee_cnt), 0) AS emp,
               avg(coalesce(delay_minutes, 0)) AS avg_delay,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
        {extra}
        GROUP BY 1 ORDER BY 1
    """
    rows = _rows(con, sql)
    total = sum(r[1] for r in rows) or 1
    days = max(w["historyDays"], 1)
    return [{
        "hour": int(h),
        "tripsPerDay": round(trips / days, 1),
        "shareOfDay": round(trips / total, 4),
        "employeesPerTrip": round(emp / trips, 2) if trips else 0.0,
        "avgDelayMin": _r(avg_delay),
        "onTimePct": _pct(ontime, trips),
    } for h, trips, emp, avg_delay, ontime in rows]



def _by_band(con, w, off, weekday: int | None = None) -> list[dict]:
    """Shift band x direction, the grain a shift roster is actually written
    at. Same `weekday` restriction as `_by_hour`, for the same reason."""
    extra = ""
    if weekday is not None:
        extra = (f"AND ((({_local_expr('scheduled_at', off)} // {DAY_MS}) + 3) % 7) "
                 f"= {weekday}")
    sql = f"""
        SELECT coalesce(shift_band, 'UNKNOWN') AS band,
               coalesce(trip_direction, 'UNKNOWN') AS direction,
               count(*) AS trips,
               coalesce(sum(plannedemployee_cnt), 0) AS emp,
               avg(coalesce(delay_minutes, 0)) AS avg_delay,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime,
               avg(CASE WHEN actual_cab_capacity > 0
                        THEN actualemployee_cnt * 1.0 / actual_cab_capacity END) AS occupancy
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
        {extra}
        GROUP BY 1, 2 ORDER BY 3 DESC
    """
    rows = _rows(con, sql)
    total = sum(r[2] for r in rows) or 1
    days = max(w["historyDays"], 1)
    return [{
        "band": band,
        "direction": direction,
        "tripsPerDay": round(trips / days, 1),
        "shareOfDay": round(trips / total, 4),
        "employeesPerTrip": round(emp / trips, 2) if trips else 0.0,
        "avgDelayMin": _r(avg_delay),
        "onTimePct": _pct(ontime, trips),
        "avgOccupancy": _r(occ, 2),
    } for band, direction, trips, emp, avg_delay, ontime, occ in rows]


def _same_weekday(con, w, off) -> list[dict]:
    """The four most recent matching weekdays -- the forecast's own base."""
    sql = f"""
        SELECT {_local_expr('scheduled_at', off)} // {DAY_MS} AS d,
               count(*) AS trips,
               coalesce(sum(plannedemployee_cnt), 0) AS emp
        FROM trips
        WHERE scheduled_at < {w['windowEndMs']}
          AND (({_local_expr('scheduled_at', off)} // {DAY_MS}) % 7)
              = ({w['targetDayEpoch']} % 7)
        GROUP BY 1 ORDER BY 1 DESC LIMIT 4
    """
    return [{"date": _epoch_day_to_date(d), "trips": int(t), "plannedEmployees": int(e)}
            for d, t, e in _rows(con, sql)]


def _reliability(con, w) -> dict:
    sql = f"""
        SELECT count(*) AS trips,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime,
               avg(coalesce(delay_minutes, 0)) AS avg_delay,
               quantile_cont(coalesce(delay_minutes, 0), 0.9) AS p90_delay,
               sum(CASE WHEN coalesce(delay_reason,'NODELAY') <> 'NODELAY' THEN 1 ELSE 0 END) AS delayed,
               sum(CASE WHEN is_driver_nc THEN 1 ELSE 0 END) AS driver_nc,
               sum(CASE WHEN is_cab_nc THEN 1 ELSE 0 END) AS cab_nc,
               coalesce(sum(noshow_cnt), 0) AS noshows,
               coalesce(sum(plannedemployee_cnt), 0) AS planned_emp,
               avg(CASE WHEN actual_cab_capacity > 0
                        THEN actualemployee_cnt * 1.0 / actual_cab_capacity END) AS occupancy,
               avg(planned_km) AS planned_km, avg(traveled_km) AS traveled_km
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
    """
    (trips, ontime, avg_delay, p90, delayed, dnc, cnc, noshows, pemp,
     occ, pkm, tkm) = _rows(con, sql)[0]
    reasons = _rows(con, f"""
        SELECT delay_reason, count(*) c FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
          AND coalesce(delay_reason, 'NODELAY') <> 'NODELAY'
        GROUP BY 1 ORDER BY 2 DESC LIMIT 5
    """)
    return {
        "trips": int(trips or 0),
        "onTimePct": _pct(ontime or 0, trips or 0),
        "onTimeDefinition": f"delay_minutes <= {C.ON_TIME_GRACE_MIN} (MoveInSync's own column)",
        "avgDelayMin": _r(avg_delay),
        "p90DelayMin": _r(p90),
        "delayedTripPct": _pct(delayed or 0, trips or 0),
        "driverNonCompliancePct": _pct(dnc or 0, trips or 0),
        "cabNonCompliancePct": _pct(cnc or 0, trips or 0),
        "noShowPct": _pct(noshows or 0, pemp or 0),
        "avgOccupancy": _r(occ, 2),
        "avgPlannedKm": _r(pkm),
        "avgTraveledKm": _r(tkm),
        "topDelayReasons": [{"reason": r, "trips": int(c)} for r, c in reasons],
    }


def _vendors(con, w, limit: int = 6) -> list[dict]:
    sql = f"""
        SELECT vendor_id, count(*) AS trips,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime,
               avg(coalesce(delay_minutes, 0)) AS avg_delay
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
          AND vendor_id IS NOT NULL
        GROUP BY 1 HAVING count(*) >= {C.MIN_ROWS_PER_SLICE}
        ORDER BY 2 DESC LIMIT {limit}
    """
    days = max(w["historyDays"], 1)
    return [{"vendor": v, "tripsPerDay": round(t / days, 1),
             "onTimePct": _pct(o, t), "avgDelayMin": _r(d)}
            for v, t, o, d in _rows(con, sql)]


def _sites(con, w, limit: int = 6) -> list[dict]:
    sql = f"""
        SELECT coalesce(site_id, 'UNKNOWN') AS site, count(*) AS trips,
               coalesce(sum(plannedemployee_cnt), 0) AS emp,
               sum(CASE WHEN {_ONTIME} THEN 1 ELSE 0 END) AS ontime
        FROM trips
        WHERE scheduled_at >= {w['windowStartMs']} AND scheduled_at < {w['windowEndMs']}
        GROUP BY 1 ORDER BY 2 DESC LIMIT {limit}
    """
    days = max(w["historyDays"], 1)
    return [{"site": s, "tripsPerDay": round(t / days, 1),
             "employeesPerDay": round(e / days, 1), "onTimePct": _pct(o, t)}
            for s, t, e, o in _rows(con, sql)]


def _alerts(con, w) -> dict:
    try:
        rows = _rows(con, f"""
            SELECT a.event_type, coalesce(a.severity, 'UNRATED') AS sev, count(*) c
            FROM alerts a JOIN trips t ON t.trip_id = a.trip_id
            WHERE t.scheduled_at >= {w['windowStartMs']} AND t.scheduled_at < {w['windowEndMs']}
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8
        """)
    except duckdb.Error:
        return {"perDay": [], "note": "alerts feed not joinable"}
    days = max(w["historyDays"], 1)
    return {"perDay": [{"eventType": e, "severity": s, "perDay": round(c / days, 2)}
                       for e, s, c in rows]}


def _boarding(con, w) -> dict:
    try:
        rows = _rows(con, f"""
            SELECT coalesce(e.boarding_status, 'UNKNOWN') AS st, count(*) c
            FROM emp_legs e JOIN trips t ON t.trip_id = e.trip_id
            WHERE t.scheduled_at >= {w['windowStartMs']} AND t.scheduled_at < {w['windowEndMs']}
            GROUP BY 1 ORDER BY 2 DESC LIMIT 6
        """)
    except duckdb.Error:
        return {}
    total = sum(c for _s, c in rows) or 0
    return {"legs": total,
            "byStatus": [{"status": s, "pct": _pct(c, total)} for s, c in rows]}


def _feedback(con, w) -> dict:
    try:
        row = _rows(con, f"""
            SELECT avg(f.route_rating), avg(f.driver_rating), avg(f.cab_rating),
                   avg(f.safety_rating), count(*)
            FROM feedback f JOIN trips t ON t.trip_id = f.trip_id
            WHERE t.scheduled_at >= {w['windowStartMs']} AND t.scheduled_at < {w['windowEndMs']}
        """)[0]
    except duckdb.Error:
        return {}
    return {"responses": int(row[4] or 0), "route": _r(row[0], 2), "driver": _r(row[1], 2),
            "cab": _r(row[2], 2), "safety": _r(row[3], 2)}



def _forecast(daily, same_weekday, hour_profile, band_profile, profile_basis,
              reliability, cfg) -> dict:
    """Seasonal-naive with a clipped trend factor, split by a historical
    profile. Transparent on purpose: the model is asked to reason ABOUT this
    number, never to recompute it, and a manager has to be able to check it.

    Level: the mean of the recent matching weekdays (a Sunday is forecast
    from Sundays). With fewer than two of those, fall back to the trailing
    7-day mean and say so.

    Trend: last 14 days over the 14 before them, clipped to +/-20% so one
    holiday week cannot swing the roster.

    Split: each hour's and each band's historical SHARE of the day, applied
    to the forecast total -- not a raw per-day average, which would ignore
    the level entirely.
    """
    recent = daily[-7:] or daily
    avg_trips = sum(d["trips"] for d in recent) / len(recent) if recent else 0.0
    avg_emp_per_trip = (sum(d["plannedEmployees"] for d in recent)
                        / max(sum(d["trips"] for d in recent), 1))

    usable = [d for d in same_weekday if d["trips"] > 0]
    if len(usable) >= 2:
        level = sum(d["trips"] for d in usable) / len(usable)
        emp_per_trip = (sum(d["plannedEmployees"] for d in usable)
                        / max(sum(d["trips"] for d in usable), 1))
        basis = f"mean of the last {len(usable)} matching weekdays"
    else:
        level, emp_per_trip = avg_trips, avg_emp_per_trip
        basis = f"mean of the last {len(recent)} days (too few matching weekdays)"

    last14 = daily[-14:]
    prev14 = daily[-28:-14]
    trend = 1.0
    if len(last14) >= 7 and len(prev14) >= 7:
        a = sum(d["trips"] for d in last14) / len(last14)
        b = sum(d["trips"] for d in prev14) / len(prev14)
        if b:
            trend = min(1.2, max(0.8, a / b))

    trips = level * trend
    employees = trips * emp_per_trip
    buffer = 1.0 + cfg.capacity_buffer_pct / 100.0

    peaks = []
    for h in sorted(hour_profile, key=lambda x: x["shareOfDay"], reverse=True)[:cfg.peak_hours]:
        peaks.append({
            "hour": h["hour"],
            "window": f"{h['hour']:02d}:00-{(h['hour'] + 1) % 24:02d}:00",
            "shareOfDayPct": round(h["shareOfDay"] * 100, 1),
            "forecastTrips": round(trips * h["shareOfDay"], 1),
            "forecastEmployees": round(trips * h["shareOfDay"] * h["employeesPerTrip"], 1),
            "historicalOnTimePct": h["onTimePct"],
        })

    bands = []
    for b in sorted(band_profile, key=lambda x: x["shareOfDay"], reverse=True)[:8]:
        band_trips = trips * b["shareOfDay"]
        if band_trips < 0.05:
            continue
        bands.append({
            "band": b["band"], "direction": b["direction"],
            "shareOfDayPct": round(b["shareOfDay"] * 100, 1),
            "forecastTrips": round(band_trips, 1),
            "forecastEmployees": round(band_trips * b["employeesPerTrip"], 1),
            "vehiclesWithBuffer": max(1, round(band_trips * buffer)),
            "historicalOnTimePct": b["onTimePct"],
            "avgOccupancy": b["avgOccupancy"],
        })

    return {
        "basis": basis,
        "profileBasis": profile_basis,
        "trendFactor": round(trend, 3),
        "forecastTrips": round(trips, 1),
        "forecastEmployees": round(employees),
        "employeesPerTrip": round(emp_per_trip, 2),
        # One trip is one vehicle dispatch in this dataset -- there is no
        # separate fleet roster feed -- so vehicles required tracks trips,
        # plus a standby buffer (TRIGGER_CAPACITY_BUFFER_PCT).
        "vehiclesRequired": max(1, round(trips)),
        "vehiclesWithBuffer": max(1, round(trips * buffer)),
        "driversRequired": max(1, round(trips * buffer)),
        "bufferPct": cfg.capacity_buffer_pct,
        "peakHours": peaks,
        "byBand": bands,
        "expectedOnTimePct": reliability.get("onTimePct"),
        "expectedAvgDelayMin": reliability.get("avgDelayMin"),
    }



def build(cfg) -> dict:
    """Everything the planner needs, as one JSON-serialisable dict."""
    con, health = load(cfg.data_dir)
    try:
        off = cfg.tz_offset_min * 60_000
        w = target_window(con, cfg)
        daily = _daily(con, w, off)
        same_weekday = _same_weekday(con, w, off)
        reliability = _reliability(con, w)

        # Profile the day being planned against days that look like it, when
        # there are enough of them; otherwise against the whole window, and
        # say which was used.
        weekday_idx = datetime.strptime(w["targetDate"], "%Y-%m-%d").weekday()
        enough = len([d for d in same_weekday if d["trips"] > 0]) >= 2
        if enough:
            hour_profile = _by_hour(con, w, off, weekday_idx)
            band_profile = _by_band(con, w, off, weekday_idx)
            profile_basis = f"{w['targetWeekday']}s only, last {cfg.history_days} days"
        else:
            hour_profile = _by_hour(con, w, off)
            band_profile = _by_band(con, w, off)
            profile_basis = f"all days, last {cfg.history_days} days"

        return {
            "window": w,
            "dataDir": cfg.data_dir,
            "feedHealth": health,
            "daily": daily,
            "byHour": hour_profile,
            "byShiftBand": band_profile,
            "sameWeekdayHistory": same_weekday,
            "reliability": reliability,
            "vendors": _vendors(con, w),
            "sites": _sites(con, w),
            "alerts": _alerts(con, w),
            "boarding": _boarding(con, w),
            "feedback": _feedback(con, w),
            "forecast": _forecast(daily, same_weekday, hour_profile, band_profile,
                                  profile_basis, reliability, cfg),
        }
    finally:
        con.close()


