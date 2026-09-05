"""The ride adapter -- the ONE place that knows the data is static.

Everything downstream (delay_analyzer, escalation_agent, format) consumes
`RideContext` dicts and never touches a CSV, a SQL view or a clock. Moving to
live data means writing a second `RideSource` that fills the same dicts from
the ride-event stream; nothing else in this agent changes.

    class RideSource(Protocol):
        def now_ms(self) -> int:               ...   # the operational "now"
        def rides_in_scope(self) -> list[dict]: ...  # rides worth looking at

SIMULATING "NOW" -- stated plainly because the dataset is not real-time:
there is no live feed, so the agent picks a moment INSIDE the data and treats
it as the current time. By default that is the busiest in-flight moment in
the last week of data (the moment a Team Manager would actually be watching
-- the final day of a dataset is often a thin weekend); `TEAM_NOW` overrides
it.

WHAT IS KNOWABLE AT `now` -- and this is the part that matters. For a ride
still in flight, `actual_end_epoch` is the FUTURE and using it would be
leaking the answer. So an in-flight ride's expected arrival is PROJECTED from
what is known at `now` (when the driver actually started + the planned
duration), and every ride carries `etaBasis` saying which it is:

    projected -- ride in flight, arrival inferred from the start slip
    observed  -- ride already finished, actual arrival known

BOOKING TIME: the dataset has no booking or confirmation timestamp. The
honest proxy for "booked late" is `emp_legs.signintype = 'Adhoc'` -- a rider
added outside the planned roster -- and `not_boarding_reason =
'TRIP_CANCELLED_FROM_DASHBOARD'`, a booking pulled after the trip was formed.
Neither is a booking clock, and nothing here pretends otherwise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..common import data as data_mod

logger = logging.getLogger("trigger")

MIN_MS = 60_000
IN_FLIGHT, UPCOMING, RECENTLY_COMPLETED = "IN_FLIGHT", "UPCOMING", "RECENTLY_COMPLETED"


def _local(ms, off_min: int) -> str | None:
    if ms is None:
        return None
    tz = timezone(timedelta(minutes=off_min))
    return datetime.fromtimestamp(ms / 1000, tz).strftime("%Y-%m-%d %H:%M")


def _mins(a, b):
    """(a - b) in whole minutes, or None if either side is missing."""
    if a is None or b is None:
        return None
    return round((a - b) / MIN_MS)


class StaticCsvRideSource:
    """Reads the committed CSVs through the repository's own ingest layer."""

    SCAN_DAYS = 7        # how far back to look for the busiest moment

    def __init__(self, cfg):
        self.cfg = cfg
        self.con, self.health = data_mod.connect(cfg.data_dir)
        data_mod.ops_view(self.con)
        self._now = self._resolve_now()

    # -- the clock ---------------------------------------------------------

    def _resolve_now(self) -> int:
        off = self.cfg.tz_offset_min * MIN_MS
        if self.cfg.now:
            dt = datetime.strptime(self.cfg.now, "%Y-%m-%d %H:%M")
            return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000) - off
        row = self.con.sql("""
            SELECT max(coalesce(actual_at, planned_end_at)) FROM trip_ops
        """).fetchone()
        if not row or row[0] is None:
            raise ValueError("no trips with a usable timestamp")
        last_ms = int(row[0])
        day_start = ((last_ms + off) // 86_400_000) * 86_400_000 - off
        # Scan the last SCAN_DAYS days, not just the final one: the last day
        # in a dataset is often a thin weekend, and the moment worth watching
        # is the busiest one, wherever it falls.
        scan_from = day_start - (self.SCAN_DAYS - 1) * 86_400_000
        rows = self.con.sql(f"""
            SELECT coalesce(actual_start_at, scheduled_at) AS s,
                   coalesce(actual_at, planned_end_at) AS e
            FROM trip_ops
            WHERE coalesce(actual_start_at, scheduled_at) >= {scan_from}
              AND coalesce(actual_start_at, scheduled_at) < {day_start + 86_400_000}
              AND coalesce(actual_at, planned_end_at) IS NOT NULL
              -- a start more than a day after its own arrival is corrupt, not
              -- a ride; it must not decide the clock
              AND coalesce(actual_at, planned_end_at) > coalesce(actual_start_at, scheduled_at)
        """).fetchall()
        if not rows:
            return last_ms
        best, best_n = last_ms, -1
        slots = self.SCAN_DAYS * 96
        for slot in range(slots):
            t = scan_from + slot * 15 * MIN_MS
            n = sum(1 for s, e in rows if s <= t < e)
            if n > best_n:
                best, best_n = t, n
        logger.info("trigger: simulated now = %s (%d rides in flight)",
                    _local(best, self.cfg.tz_offset_min), best_n)
        return best

    def now_ms(self) -> int:
        return self._now

    # -- the rides ---------------------------------------------------------

    def rides_in_scope(self) -> list[dict]:
        """Rides a Team Manager could still act on at `now`: in flight,
        starting shortly, or finished recently enough that the fallout (a
        late arrival, a stranded rider) is still live."""
        cfg, now = self.cfg, self._now
        lo = now - cfg.lookback_min * MIN_MS
        hi = now + cfg.lookahead_min * MIN_MS
        rows = self.con.sql(f"""
            WITH legs AS (
                SELECT trip_id,
                       count(*) AS legs,
                       sum(CASE WHEN signintype = 'Adhoc' THEN 1 ELSE 0 END) AS adhoc_legs,
                       sum(CASE WHEN signintype = 'Guest' THEN 1 ELSE 0 END) AS guest_legs,
                       sum(CASE WHEN signintype IS NULL THEN 1 ELSE 0 END) AS unknown_signin,
                       sum(CASE WHEN not_boarding_reason = 'TRIP_CANCELLED_FROM_DASHBOARD'
                                THEN 1 ELSE 0 END) AS cancelled_legs,
                       sum(CASE WHEN not_boarding_reason = 'NO_SHOW' THEN 1 ELSE 0 END) AS noshow_legs,
                       sum(CASE WHEN boarding_status = 'Not Boarded' THEN 1 ELSE 0 END) AS not_boarded,
                       max(actual_pickup_at - planned_pickup_at) AS max_pickup_slip_ms,
                       min(planned_pickup_at) AS first_planned_pickup
                FROM emp_legs GROUP BY 1
            ), alert AS (
                SELECT trip_id, count(*) AS alerts,
                       string_agg(DISTINCT event_type, ', ') AS event_types,
                       min(severity) AS worst_severity
                FROM alerts GROUP BY 1
            )
            SELECT o.trip_id, o.vendor_id, o.site_id, o.business_unit, o.trip_direction,
                   o.mode, o.shift_band, o.shift_type, o.route_source,
                   o.scheduled_at, o.actual_start_at, o.planned_end_at, o.actual_at,
                   o.delay_minutes, o.delay_reason, o.is_driver_nc, o.is_cab_nc,
                   o.plannedemployee_cnt, o.actualemployee_cnt, o.noshow_cnt,
                   o.actual_cab_capacity, o.planned_km, o.traveled_km, o.actual_escort,
                   l.legs, l.adhoc_legs, l.guest_legs, l.unknown_signin, l.cancelled_legs,
                   l.noshow_legs, l.not_boarded, l.max_pickup_slip_ms, l.first_planned_pickup,
                   a.alerts, a.event_types, a.worst_severity
            FROM trip_ops o
            LEFT JOIN legs  l USING (trip_id)
            LEFT JOIN alert a USING (trip_id)
            WHERE coalesce(o.actual_start_at, o.scheduled_at) <= {hi}
              AND coalesce(o.actual_at, o.planned_end_at, o.scheduled_at) >= {lo}
        """).fetchall()
        out = []
        for r in rows:
            try:
                ride = self._to_context(r)
            except Exception as exc:        # one malformed row, not the run
                logger.warning("trigger: skipped a ride row (%s)", type(exc).__name__)
                continue
            if ride is not None:
                out.append(ride)
        return out

    def _to_context(self, r) -> dict | None:
        (trip_id, vendor, site, bu, direction, mode, band, shift_type, route_source,
         scheduled_at, actual_start_at, planned_end_at, actual_at,
         delay_minutes, delay_reason, driver_nc, cab_nc,
         planned_emp, actual_emp, noshow_cnt, capacity, planned_km, traveled_km, escort,
         legs, adhoc, guest, unknown_signin, cancelled, noshow_legs, not_boarded,
         pickup_slip_ms, first_pickup,
         alerts, event_types, worst_severity) = r

        if trip_id is None:
            return None                     # a ride with no id cannot be acted on
        cfg, now, off = self.cfg, self._now, self.cfg.tz_offset_min

        started = actual_start_at is not None and actual_start_at <= now
        ended = actual_at is not None and actual_at <= now
        if ended:
            status, eta_basis = RECENTLY_COMPLETED, "observed"
            expected_arrival = actual_at
        elif started:
            status, eta_basis = IN_FLIGHT, "projected"
            planned_duration = (planned_end_at - scheduled_at) if (
                planned_end_at is not None and scheduled_at is not None) else None
            expected_arrival = (actual_start_at + planned_duration
                                if planned_duration is not None else None)
            if expected_arrival is not None:
                expected_arrival = max(expected_arrival, now)
        else:
            status, eta_basis = UPCOMING, "planned"
            expected_arrival = planned_end_at

        return {
            "rideId": str(trip_id),
            "status": status,
            "etaBasis": eta_basis,
            "nowLocal": _local(now, off),
            "vendor": vendor, "site": site, "businessUnit": bu,
            "direction": direction, "mode": mode,
            "shiftBand": band, "shiftType": shift_type, "routeSource": route_source,
            "scheduledStartLocal": _local(scheduled_at, off),
            # A ride that has not started yet has no ACTUAL start at `now`
            # -- the column holds one, but it is in the future. Reporting it
            # would leak exactly the information the live system would not
            # have, so it is withheld until the ride is under way.
            "actualStartLocal": _local(actual_start_at, off) if started else None,
            "plannedArrivalLocal": _local(planned_end_at, off),
            "expectedArrivalLocal": _local(expected_arrival, off),
            "actualArrivalLocal": _local(actual_at, off) if ended else None,
            "driverStartSlipMin": (_mins(actual_start_at, scheduled_at)
                                   if started else None),
            "etaDeviationMin": _mins(expected_arrival, planned_end_at),
            "plannedDurationMin": _mins(planned_end_at, scheduled_at),
            "elapsedMin": _mins(now, actual_start_at) if started else None,
            "minutesToStart": _mins(scheduled_at, now) if status == UPCOMING else None,
            "overdueMin": (_mins(now, planned_end_at)
                           if (not ended and planned_end_at is not None
                               and now > planned_end_at) else None),
            "moveInSyncDelayMin": int(delay_minutes) if delay_minutes is not None else None,
            "delayReason": delay_reason,
            "driverNonCompliance": bool(driver_nc) if driver_nc is not None else None,
            "cabNonCompliance": bool(cab_nc) if cab_nc is not None else None,
            "plannedRiders": int(planned_emp) if planned_emp is not None else None,
            "actualRiders": int(actual_emp) if actual_emp is not None else None,
            "noShowRiders": int(noshow_cnt) if noshow_cnt is not None else None,
            "cabCapacity": int(capacity) if capacity is not None else None,
            "legs": int(legs) if legs is not None else None,
            "adhocLegs": int(adhoc) if adhoc is not None else 0,
            "guestLegs": int(guest) if guest is not None else 0,
            "unknownSignInLegs": int(unknown_signin) if unknown_signin is not None else 0,
            "cancelledLegs": int(cancelled) if cancelled is not None else 0,
            "noShowLegs": int(noshow_legs) if noshow_legs is not None else 0,
            "notBoardedLegs": int(not_boarded) if not_boarded is not None else 0,
            "maxPickupSlipMin": (round(pickup_slip_ms / MIN_MS)
                                 if pickup_slip_ms is not None else None),
            "firstPickupLocal": _local(first_pickup, off),
            "plannedKm": float(planned_km) if planned_km is not None else None,
            "traveledKm": float(traveled_km) if traveled_km is not None else None,
            "escortPresent": escort,
            "alertCount": int(alerts) if alerts is not None else 0,
            "alertTypes": event_types,
            "worstAlertSeverity": worst_severity,
        }

    def close(self) -> None:
        self.con.close()
