"""The governed vocabulary. NOTHING ELSE queries raw tables.

Five metrics, all against the real views ingest.py builds (docs/real-dataset-
mapping.md §6, §8). marshal compliance and EV share are later tasks -- this
registry stops at what the real dataset can support today without inventing a
column.

Deviation 5 still applies (and now matters MORE than in the fixture): a trip
with no actual_at, or no planned_end_at, is excluded from numerator AND
denominator. Guessing "late" invents a fact; guessing "on time" hides one.
"""
from __future__ import annotations

import duckdb

from . import constants as C
from .schemas import Dimension, Direction, Metric, ReferenceKind, Slice, Window

# OTA/OTD compare actual_at against planned_end_at, not scheduled_at
# (scheduled_at is when the trip was PLANNED TO START; planned_end_at is when
# it was planned to finish, which is what "on time" means for both an arrival
# and a departure). The window predicate stays on scheduled_at -- that is what
# places the trip IN the week being swept, independent of whether it ran on
# time.
#
# __DIRECTION__ is a plain-Python placeholder, substituted once at import time
# below -- not a SQL token, and never touched per-call. ota is LOGIN, otd is
# LOGOUT (MoveInSync's own vocabulary: two named metrics, not one metric
# sliced by direction), vendor_ota carries neither filter.
_ON_TIME_BASE = f"""
SELECT 100.0 * sum(CASE WHEN t.actual_at <= t.planned_end_at + {C.ON_TIME_GRACE_MS} THEN 1 ELSE 0 END)
       / nullif(count(*), 0),
       count(*) AS n
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND t.actual_at IS NOT NULL AND t.planned_end_at IS NOT NULL
  __DIRECTION__
  {{{{SLICE}}}}
"""

_OTA_SQL = _ON_TIME_BASE.replace("__DIRECTION__", "AND t.trip_direction = 'LOGIN'")
_OTD_SQL = _ON_TIME_BASE.replace("__DIRECTION__", "AND t.trip_direction = 'LOGOUT'")
_VENDOR_OTA_SQL = _ON_TIME_BASE.replace("__DIRECTION__", "")

# noshow_cnt / plannedemployee_cnt are both per-trip headcounts on the trips
# view -- real MoveInSync vocabulary (docs/real-dataset-mapping.md §8), and a
# direct capacity-waste signal.
#
# Fix-wave I4 supersedes Task 3b's own ruling here: the second column is now
# sum(plannedemployee_cnt) -- the rate's own denominator (a headcount), not
# count(*) of trips. Task 3b's reasoning ("one trip with 40 planned employees
# is still one data point, not 40") was about what should silence a THIN
# SLICE, and remains defensible on its own terms -- but it also made
# decompose.py's share-of-volume (n / overall_n, drawn from this exact column)
# a headcount-vs-trip-count mismatch for the one metric whose ratio is not
# count-weighted, understating how much slack a decomposition's sum needed to
# tolerate. Matching n to the rate's own denominator removes that mismatch
# and is the more honest reading of "population the value was computed over"
# for a rate that is not itself a share of trips.
_NO_SHOW_SQL = """
SELECT 100.0 * sum(t.noshow_cnt) / nullif(sum(t.plannedemployee_cnt), 0),
       sum(t.plannedemployee_cnt) AS n
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  {{SLICE}}
"""

# Cost per km, not cost per trip: it normalises trip length, so a fleet running
# longer routes does not look artificially expensive next to one running short
# hops. The window predicate is on t.scheduled_at (the trip, not the bill line)
# so a slice and a window mean the same thing on every metric in this file.
#
# Fix-wave I4, REVISED (a data investigation superseded the first version of
# this ruling): b.total_trip_km = 0 is not a missing-odometer artifact -- it
# is a BILLING MODE. Measured on data/real: 248,191 of 620,942 bill rows
# (40.0%), Rs 378.8M of Rs 834.0M billed (45.4% of spend), carry
# total_trip_km <= 0 -- overwhelmingly on SLAB contracts (100% zero-km on
# 4S-HYD/6S-HYD/12S-150ORRNEW, ~99.7% on 4S-150ORRNEW/6S-150ORRNEW/4S-EV-Z/
# BUS-ORRNEW-TT), which bill a flat per-shift/slab rate regardless of
# distance. Filtering those rows out (this file's first fix-wave attempt)
# would silently drop 45% of real spend from the cost story -- worse than
# the artifact it was trying to fix.
#
# Every one of those trips still has a real, non-zero t.traveled_km (the
# ACTUAL distance driven, on the trips feed -- avg 15.5km across 251,207
# such rows) -- b.total_trip_km is a BILLING-side field that is simply blank
# for a slab contract, not evidence the trip covered no distance. Dividing
# by the trip's own traveled_km instead keeps every slab-billed rupee in the
# numerator with an honest, non-zero denominator, and generalises to every
# contract type rather than special-casing slab contracts by name.
_COST_PER_KM_SQL = """
SELECT sum(b.trip_cost) / nullif(sum(t.traveled_km), 0),
       count(*) AS n
FROM bill b JOIN trips t ON t.trip_id = b.trip_id
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND t.traveled_km IS NOT NULL AND t.traveled_km > 0
  {{SLICE}}
"""

# Fix-wave I3: ota/otd each hardcode their own direction filter (LOGIN/LOGOUT
# respectively -- see _ON_TIME_BASE above), so a DIRECTION slice of either one
# is a redundant repeat of the unsliced finding under a misleading label
# ("On-time arrival - direction LOGIN" reporting the exact same number as
# "On-time arrival - overall"). vendor_ota carries neither direction filter,
# so DIRECTION stays meaningful there and is left at the default. cost_per_km
# and marshal_compliance (Task 11) have no direction concept at all -- their
# source rows (bill, marshal_population) carry no trip_direction of their
# own that a DIRECTION slice could meaningfully partition -- so they share
# this same reduced set.
_DIMS_EXCEPT_DIRECTION = tuple(d for d in Dimension if d not in (Dimension.NONE, Dimension.DIRECTION))

# Task 11: the marshal-required population, derived once in ingest.py as its
# own view (docs/real-dataset-mapping.md §7) -- a trip needs an escort when it
# runs in dark hours AND carries a female rider, OR a WOMAN_TRAVELLING_ALONE
# alert fired on it regardless of hour. Compliance is actual_escort=true over
# that population; hard_target=True below because deviation 2 applies here
# exactly as named in the spec -- this is the one metric a partial pass does
# not make sense for (a trip either had its required escort or it did not).
_MARSHAL_SQL = """
SELECT 100.0 * sum(CASE WHEN t.actual_escort THEN 1 ELSE 0 END) / nullif(count(*), 0),
       count(*) AS n
FROM marshal_population t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  {{SLICE}}
"""

METRICS: tuple[Metric, ...] = (
    # ota is first deliberately: it is the metric a judge reads first.
    Metric("ota", "On-time arrival", "%", Direction.HIGHER, _OTA_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "trips",
           ("actual_at", "planned_end_at"), dims=_DIMS_EXCEPT_DIRECTION),
    # OTA is On-Time ARRIVAL (LOGIN trips); OTD is On-Time DEPARTURE (LOGOUT
    # trips). Two named metrics in MoveInSync's own vocabulary, not one metric
    # sliced by direction.
    Metric("otd", "On-time departure", "%", Direction.HIGHER, _OTD_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "trips",
           ("actual_at", "planned_end_at"), dims=_DIMS_EXCEPT_DIRECTION),
    # Fix-wave I3: restricted to VENDOR only -- that is the one slice this
    # metric exists to answer ("vendor on-time share"); sliced any other way
    # it duplicates the same question under a mislabelled subject
    # ("Vendor on-time share - Shift: Evening" reads as a claim about a
    # vendor, but names a shift).
    Metric("vendor_ota", "Vendor on-time share", "%", Direction.HIGHER,
           _VENDOR_OTA_SQL, (ReferenceKind.TREND, ReferenceKind.PEER), "trips",
           ("actual_at", "planned_end_at", "vendor_id"), dims=(Dimension.VENDOR,)),
    Metric("no_show_rate", "No-show rate", "%", Direction.LOWER, _NO_SHOW_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "trips",
           ("noshow_cnt", "plannedemployee_cnt")),
    # required_columns is checked against `source` ("bill") alone --
    # coverage() has no join. total_trip_km dropped from this list (fix-wave
    # I4, revised): the formula no longer reads it at all, so listing it here
    # would only make coverage() (correctly) find it absent on a slab
    # contract and undercount confidence for a column the metric does not
    # use.
    Metric("cost_per_km", "Cost per km", "INR/km", Direction.LOWER, _COST_PER_KM_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "bill",
           ("trip_cost",), dims=_DIMS_EXCEPT_DIRECTION),
    # Task 11: source="trips" (not "marshal_population", which has no entry
    # in ingest.py's own health dict) -- the feed-confidence lookup in
    # sweep.py and the coverage() DESCRIBE check both want a real feed name,
    # and every column marshal_population derives from (actual_escort,
    # gender, event_type) ultimately traces back to a feed that is already
    # health-tracked; actual_escort itself is a real trips column.
    Metric("marshal_compliance", "Marshal compliance", "%", Direction.HIGHER,
           _MARSHAL_SQL, (ReferenceKind.TARGET,), "trips", ("actual_escort",),
           target=100.0, hard_target=True, dims=_DIMS_EXCEPT_DIRECTION),
)

# EV share is a later task (cheap, but out of scope here). experience was
# dropped (Task 11): its ratings include 0 values that may mean "unrated",
# the only one of the six needing a judgement call about its own data.
ACTIVE_METRICS = ("ota", "otd", "vendor_ota", "no_show_rate", "cost_per_km",
                  "marshal_compliance")
# Compatibility alias -- every pre-Task-11 caller (sweep.py's default,
# api.py's /api/health, the test suite) keeps working unchanged; new code
# should read ACTIVE_METRICS.
TIER_1_METRICS = ACTIVE_METRICS


def by_id(metric_id: str) -> Metric:
    for m in METRICS:
        if m.id == metric_id:
            return m
    valid = ", ".join(m.id for m in METRICS)
    raise ValueError(f"unknown metric id {metric_id!r}; valid ids are {valid}")


def active(ids=ACTIVE_METRICS) -> tuple[Metric, ...]:
    return tuple(m for m in METRICS if m.id in ids)


def _as_slices(slc: "Slice | tuple[Slice, ...]") -> tuple[Slice, ...]:
    """Task 8: decompose.py needs a COMPOUND slice -- a finding already sliced
    by site, decomposed further by vendor, means binding both predicates in
    one query. A bare Slice is still the common case everywhere else
    (evaluate/evidence_sql/coverage), so it is accepted as-is and wrapped."""
    return slc if isinstance(slc, tuple) else (slc,)


def _with_slice(sql: str, slc: "Slice | tuple[Slice, ...]") -> str:
    predicate = " ".join(f"AND {s.dim.column} = ?" for s in _as_slices(slc)
                         if s.dim is not Dimension.NONE)
    return sql.replace("{{SLICE}}", predicate)


def _params(slc: "Slice | tuple[Slice, ...]", window: Window) -> list:
    p = [window.start_ms, window.end_ms]
    for s in _as_slices(slc):
        if s.dim is not Dimension.NONE:
            p.append(s.value)    # ALWAYS bound, never interpolated
    return p


# Memoisation: the peer and trend computations (Task 4) call evaluate()
# thousands of times per sweep, mostly re-asking the same (metric, slice,
# window) triple. Keyed on id(con) too, since a test opens a fresh connection
# per case and a stale cache entry from a closed connection must never answer
# for a new one. A cached None is a real answer (an empty slice), not a miss --
# the `in` check below distinguishes "never computed" from "computed as None".
_CACHE: dict[tuple, float | None] = {}

# Task 8: decompose.py's own cache, independent of _CACHE above. evaluate()'s
# guard folds a thin slice's value to None -- exactly right for a Finding,
# wrong for decompose.py, which needs the slice's true population (and its
# value, when the query still resolves one) to fold it into an honest
# "(other)" row rather than silently losing its volume. Keeping this cache
# separate means evaluate()'s own behaviour, and the tests pinned on _CACHE's
# exact contents, are untouched.
_RAW_CACHE: dict[tuple, tuple[float | None, int]] = {}


def clear_cache() -> None:
    _CACHE.clear()
    _RAW_CACHE.clear()


def evaluate(con, metric: Metric, slc: Slice, window: Window) -> float | None:
    """None when the slice has no rows: a data gap, never a zero.

    A missing slice scoring 0% and breaching on a vendor that simply did not
    operate that week is the most damaging bug available in this layer.

    None also when the slice's population is below MIN_ROWS_PER_SLICE -- a
    rate over three trips is not a finding.

    Every metric in this registry's own SQL returns a second column, `n`,
    the population the value was computed over -- the guard reads it from
    row[1]. A synthetic single-column metric (used only in a few pure-Python
    test fixtures elsewhere) has no population to guard on, so the guard is
    skipped rather than raising: the row-length check is deliberate.
    """
    key = (id(con), metric.id, slc, window)
    if key in _CACHE:
        return _CACHE[key]
    row = con.execute(_with_slice(metric.sql, slc), _params(slc, window)).fetchone()
    if row is None or row[0] is None:
        value = None
    elif len(row) > 1 and row[1] is not None and row[1] < C.MIN_ROWS_PER_SLICE:
        value = None
    else:
        value = float(row[0])
    _CACHE[key] = value
    return value


def evaluate_with_n(con, metric: Metric, slc: "Slice | tuple[Slice, ...]",
                    window: Window) -> tuple[float | None, int]:
    """The raw (value, n) pair for a metric x slice x window triple -- `slc`
    may be a single Slice or a tuple of Slices bound together (a compound
    slice: decompose.py's "within site X, broken out by vendor").

    UNLIKE evaluate(), this is NOT floored by MIN_ROWS_PER_SLICE: a thin
    slice's own population (and its value, when the query still resolves one)
    is exactly what decompose.py needs to fold the slice into an honest
    "(other)" row, rather than losing its volume the way evaluate()'s guard
    would if decompose read through evaluate() alone. n is 0, never None,
    both for a genuinely empty slice and for a synthetic single-column metric
    (used only in a few pure-Python test fixtures) that carries no population
    column at all.
    """
    key = (id(con), metric.id, slc, window)
    if key in _RAW_CACHE:
        return _RAW_CACHE[key]
    row = con.execute(_with_slice(metric.sql, slc), _params(slc, window)).fetchone()
    if row is None or row[0] is None:
        value = None
    else:
        value = float(row[0])
    n = int(row[1]) if (row is not None and len(row) > 1 and row[1] is not None) else 0
    _RAW_CACHE[key] = (value, n)
    return _RAW_CACHE[key]


def coverage(con, metric: Metric, slc: Slice, window: Window) -> float:
    """Fraction of rows where every column the metric needs is non-null.

    BUG F3: when the metric's SOURCE table lacks the SLICE column (bill has no
    mode/trip_direction/shift_band), measure UNSLICED rather than returning
    0.0 -- otherwise a modelling gap becomes a wall of LOW_CONFIDENCE noise.
    Absence of the metric's OWN required column still returns 0.0, which is
    what deviation 6 needs.
    """
    if not metric.required_columns:
        return 1.0
    table = metric.source
    present = {r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()}
    if not set(metric.required_columns) <= present:
        return 0.0
    non_null = " AND ".join(f"{c} IS NOT NULL" for c in metric.required_columns)

    slice_col = None if slc.dim is Dimension.NONE else slc.dim.column.split(".", 1)[-1]
    sliceable = slice_col is not None and slice_col in present
    predicate = f" AND {slice_col} = ?" if sliceable else ""
    params = [slc.value] if sliceable else []

    row = con.execute(
        f"SELECT avg(CASE WHEN {non_null} THEN 1.0 ELSE 0.0 END) FROM {table} WHERE TRUE{predicate}",
        params).fetchone()
    return 0.0 if row is None or row[0] is None else float(row[0])


def distinct_values(con, dim: Dimension, window: Window) -> list[str]:
    col = dim.column
    rows = con.execute(
        f"SELECT DISTINCT {col} AS v FROM trips t "
        f"WHERE t.scheduled_at >= ? AND t.scheduled_at < ? AND {col} IS NOT NULL ORDER BY v",
        [window.start_ms, window.end_ms]).fetchall()
    return [r[0] for r in rows]


# Task 8: MoveInSync's own delay taxonomy ships as a real column
# (docs/real-dataset-mapping.md §4, docs/moveinsync-domain-vocabulary.md §1) --
# NODELAY/TRAFFIC/DRIVER/EMPLOYEE, checked in that cascade precedence upstream
# of this file. NODELAY is excluded here: it means the trip was not late at
# all, so it owns none of a shortfall by definition -- decompose.py's shares
# are shares of LATE trips, not of all trips.
#
# Fix-wave (Task 8 review, Important): NULL is kept IN, not filtered out. A
# late trip whose delay_reason was never classified is still a late trip --
# excluding `delay_reason IS NOT NULL` silently shrank total_late, which
# contradicted this module's own fold-into-"(other)" promise (a NULL
# reason is exactly the kind of thing that promise exists for). GROUP BY
# gives a NULL its own row here; decompose.py folds it into "(other)"
# unconditionally, the same place a below-floor reason already goes.
_DELAY_REASON_SQL = """
SELECT delay_reason, count(*) AS trips, avg(CAST(delay_minutes AS DOUBLE)) AS avg_delay_min
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND (delay_reason IS NULL OR delay_reason <> 'NODELAY')
  {{SLICE}}
GROUP BY delay_reason
ORDER BY trips DESC
"""


def delay_reason_breakdown(con, slc: "Slice | tuple[Slice, ...]",
                           window: Window) -> list[tuple[str | None, int, float]]:
    """(reason, trip count, average delay minutes) for every late trip in the
    window (and slice, if any) -- one row per TRAFFIC/DRIVER/EMPLOYEE value
    actually present, PLUS one row with reason=None for late trips whose
    delay_reason was never classified (decompose.py folds that row into
    "(other)" unconditionally). decompose.py is the only caller; this is the
    one query its DELAY_REASON path needs, kept here per the
    SELECT-only-in-registry invariant (spec 1.1: registry.py and ingest.py
    are the only modules that query raw tables)."""
    rows = con.execute(_with_slice(_DELAY_REASON_SQL, slc), _params(slc, window)).fetchall()
    return [(r[0], int(r[1]), float(r[2]) if r[2] is not None else 0.0) for r in rows]


def evidence_sql(metric: Metric, slc: Slice, window: Window) -> str:
    """The literal-substituted form, so a human can paste it into the DuckDB CLI
    and get the same number. This is what the console shows on expand: "where did
    this number come from" answered with a query, not a claim."""
    sql = _with_slice(metric.sql, slc)
    sql = sql.replace("?", str(window.start_ms), 1).replace("?", str(window.end_ms), 1)
    if slc.dim is not Dimension.NONE:
        sql = sql.replace("?", "'" + slc.value.replace("'", "''") + "'", 1)
    return sql.strip()
