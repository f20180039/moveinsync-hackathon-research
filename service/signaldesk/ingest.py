"""Tolerant load. Loud about what it cannot read.

The CSV reader's silent-skip flag (spelled with an underscore in DuckDB's own
docs, not written out here so the grep-as-a-test in test_ingest.py can prove it
is never called) is FORBIDDEN: it has a known defect where it silently drops
VALID rows, and silent loss is the opposite of what this product claims.
store_rejects keeps every failure inspectable instead.
"""
from __future__ import annotations

import glob as _glob
import os

import duckdb

from .schemas import FeedHealth

# The five REAL feeds. There is no gps_pings file and no delays file -- delay is
# a COLUMN on the trip row. See docs/real-dataset-mapping.md §1.
FEEDS = ("trips", "emp_legs", "feedback", "bill", "alerts")

# Real-data filenames, relative to the dataset directory. Note the space in the
# trip filenames: "Ride_data _trip-may_2026.csv". data/sample/ instead uses
# plain "<feed>.csv" for every feed; source_for() below detects which layout it
# is looking at per feed rather than requiring a config flag, since a hackathon
# demo re-points SIGNALDESK_DATA at data/real without changing any other input.
GLOBS = {
    "trips":    "Ride_data*trip-*.csv",   # three monthly files, unioned by name
    "emp_legs": "emp_Data.csv",
    "feedback": "trip_feedback.csv",
    "bill":     "bill_data.csv",
    "alerts":   "alerts_data.csv",
}

# Critical columns per feed, named as they appear AFTER normalisation (the
# NORMALISE views below are what _null_critical() actually queries against).
# actual_escort is deliberately absent: a dataset without it must degrade
# marshal_compliance, not the on-time figures. Per-metric coverage in
# registry.py handles that instead.
#
# NOTE: the brief's own draft named "planned_start_epoch" / "actual_end_epoch"
# here -- the RAW column names. NORMALISE renames those to scheduled_at /
# actual_at, so left as drafted, _null_critical would find both columns
# "missing" from the post-normalisation view and mark every trips row
# critically incomplete. Fixed here to the post-normalisation names.
CRITICAL = {
    "trips":    ("trip_id", "vendor_id", "scheduled_at", "actual_at"),
    "emp_legs": ("trip_id", "stwid"),
    "feedback": ("trip_id", "route_rating"),
    # trip_id is NOT always a trip id in bill: 160 rows hold the literal string
    # 'OverHead' -- Rs 44.6 lakh of vendor charges belonging to no trip. Counting
    # them as critically incomplete is honest: they are real money we cannot
    # attribute, and that is itself worth reporting.
    "bill":     ("trip_id", "trip_cost"),
    "alerts":   ("trip_id", "event_type"),
}

# Every feed hangs off trips.trip_id. Run these AFTER normalisation, or they
# report ~100% unmatched because the three id formats never compare equal.
UNMATCHED_SQL = {
    "emp_legs": "SELECT count(*) FROM emp_legs WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "feedback": "SELECT count(*) FROM feedback WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "bill":     "SELECT count(*) FROM bill     WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "alerts":   "SELECT count(*) FROM alerts   WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
}

# One view per feed, over the materialised _raw table, presenting the names and
# units the registry expects. Every transform here is a documented quirk from
# data/real/Dictionary/README.md -- not defensive guessing.
#
# TRY_CAST, not CAST: bill.trip_id holds the literal string 'OverHead' on ~160
# rows (real vendor charges with no trip to attribute them to). CAST would
# raise and kill the whole load; TRY_CAST turns those rows into a null
# trip_id, which null_critical then counts honestly instead of the load dying.
# The same TRY_CAST is used everywhere else a comma-stripped id/number is cast,
# on the same reasoning -- a single malformed value must degrade confidence,
# not abort the ingest.
NORMALISE = {
    "trips": """
        CREATE OR REPLACE VIEW trips AS SELECT
          business_unit,
          office                AS site_id,
          product_type          AS mode,
          shift_type,
          -- trip_id is "1,097,076" here, "1123974" in bill, int64 in emp_legs.
          -- Every join returns ZERO ROWS unless all three are normalised.
          TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          trip_direction,
          vendor_id,
          actual_escort,
          -- Epoch SECONDS in the source. Multiply to ms so the schemas, the
          -- windows and the verdict engine keep working in the unit they were
          -- written for. See docs/real-dataset-mapping.md §2.
          TRY_CAST(REPLACE(CAST(planned_start_epoch AS VARCHAR), ',', '') AS BIGINT) * 1000 AS scheduled_at,
          TRY_CAST(REPLACE(CAST(actual_end_epoch   AS VARCHAR), ',', '') AS BIGINT) * 1000 AS actual_at,
          delay_reason,
          TRY_CAST(REPLACE(CAST(delay_minutes AS VARCHAR), ',', '') AS BIGINT) AS delay_minutes,
          is_driver_nc, is_cab_nc,
          -- planned_km is float in May/June but object (string) in July per the
          -- dictionary's documented dtype drift; UNION ALL BY NAME across the
          -- three monthly files then promotes the column to VARCHAR for
          -- everyone. Cast back to DOUBLE here so downstream averages don't
          -- silently become string concatenation or a binder error.
          TRY_CAST(planned_km  AS DOUBLE) AS planned_km,
          TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
          actual_cab_capacity,
          plannedemployee_cnt, actualemployee_cnt, noshow_cnt,
          actual_cab_fuel_type, trip_nodal
        FROM trips_raw
    """,
    "bill": """
        CREATE OR REPLACE VIEW bill AS SELECT
          business_unit, office AS site_id,
          vendor AS vendor_id,          -- called `vendor` here, `vendor_id` in trips
          TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          contract,
          -- slab_name carries the literal string 'null' on ~19.5% of rows, not
          -- a real NULL -- read_csv_auto does not convert it. NULLIF makes it
          -- a real null so COUNT/GROUP BY treat it as missing rather than as a
          -- fourth slab.
          NULLIF(slab_name, 'null') AS slab_name,
          total_trip_km,
          TRY_CAST(REPLACE(CAST(trip_cost AS VARCHAR), ',', '') AS BIGINT) AS trip_cost
        FROM bill_raw
    """,
    "feedback": """
        CREATE OR REPLACE VIEW feedback AS SELECT
          business_unit,
          TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          trip_type AS trip_direction,  -- different name in this file
          TRY_CAST(REPLACE(CAST(stwid AS VARCHAR), ',', '') AS BIGINT) AS stwid,
          route_rating, driver_rating, cab_rating, safety_rating, marshal_rating
        FROM feedback_raw
    """,
    # emp_legs already has clean int64 keys -- the ONE file that does.
    # Negative planned_km/traveled_km are physically impossible (down to -6.63);
    # NULL them so the gap register counts them and confidence falls, rather
    # than letting them poison an average.
    "emp_legs": """
        CREATE OR REPLACE VIEW emp_legs AS SELECT
          business_unit, office AS site_id, product_type AS mode, shift_type,
          trip_id, stwid, gender, signintype, boarding_status,
          not_boarding_reason, is_no_show,
          TRY_CAST(planned_pickup_epoch AS BIGINT) * 1000 AS planned_pickup_at,
          TRY_CAST(actual_pickup_epoch  AS BIGINT) * 1000 AS actual_pickup_at,
          CASE WHEN planned_km  < 0 THEN NULL ELSE planned_km  END AS planned_km,
          CASE WHEN traveled_km < 0 THEN NULL ELSE traveled_km END AS traveled_km
        FROM emp_legs_raw
        WHERE stwid <> 0             -- 0 is a placeholder, not a rider
    """,
    "alerts": """
        CREATE OR REPLACE VIEW alerts AS SELECT
          business_unit,
          TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          TRY_CAST(REPLACE(CAST(stwid   AS VARCHAR), ',', '') AS BIGINT) AS stwid,
          event_id, event_type, state_text, source,
          -- severity carries a stray literal "False" (and "NA") outside the
          -- enum; only the three real values survive, everything else -> NULL.
          CASE WHEN severity IN ('Sev-1','Sev-2','Sev-3') THEN severity END AS severity
        FROM alerts_raw
    """,
}


def source_for(base: str) -> callable:
    """The engine's whole knowledge of where data lives. A local directory on
    the day, an s3:// prefix in production -- the query is identical either
    way, which is what makes the deployment story an adapter swap rather than
    a rewrite.

    data/sample/ and data/real/ use different filenames (see GLOBS), so this
    detects which layout it is looking at, per feed, rather than requiring a
    separate config flag: if "<feed>.csv" exists literally, that is the sample
    layout; otherwise fall back to the real-data glob. A demo re-run just
    re-points SIGNALDESK_DATA -- nothing else changes.
    """
    base = base.rstrip("/")

    def resolve(feed: str) -> str:
        plain = f"{base}/{feed}.csv"
        if os.path.exists(plain):
            return plain
        return f"{base}/{GLOBS.get(feed, f'{feed}.csv')}"

    return resolve


def load_feed(con: duckdb.DuckDBPyConnection, feed: str, glob: str) -> FeedHealth:
    """Scan once through a tolerant reader, then materialise as a TABLE.

    BUG F2 -- why a table and not a view: a view over read_csv_auto(store_rejects)
    is lazy, so every later query re-scans the file and re-appends to the rejects
    table. Every metric query does that. Materialising costs one pass and makes
    the reject count a fact rather than a moving number.

    DuckDB (1.5.5) refuses `rejects_table` combined with `union_by_name=true` in
    a single read_csv_auto call ("REJECTS_TABLE option is not supported when
    UNION_BY_NAME is set to true") -- so a glob that expands to several files
    with different column sets (the three monthly trips files) cannot use the
    CSV reader's own union_by_name option at all. Instead: expand the glob
    ourselves, load each matched file individually with store_rejects (rejects
    from every file accumulate into the same shared rejects table -- verified;
    DuckDB does not overwrite or error on a repeated rejects_table name across
    calls), then combine the per-file staging tables with SQL's own
    `UNION ALL BY NAME`, which gives the identical column-name-based merge
    (and the identical type promotion on a name that drifts type, e.g. bool vs
    string) without needing the CSV-option that DuckDB refuses.
    """
    errors, scans = f"reject_errors_{feed}", f"reject_scans_{feed}"
    con.execute(f"DROP TABLE IF EXISTS {errors}")
    con.execute(f"DROP TABLE IF EXISTS {scans}")

    # The glob is interpolated, not bound: read_csv_auto's first argument is not
    # parameterisable. It comes from source_for(), never from a user or the
    # model, and the four tools expose no path to this function at all.
    paths = sorted(_glob.glob(glob))
    if not paths:
        raise FileNotFoundError(f"no files match {glob!r} while loading feed {feed!r}")

    stage_tables = []
    try:
        for i, path in enumerate(paths):
            safe = path.replace("'", "''")
            stage = f"_stage_{feed}_{i}"
            con.execute(f"DROP TABLE IF EXISTS {stage}")
            con.execute(f"""
                CREATE TABLE {stage} AS
                SELECT * FROM read_csv_auto(
                  '{safe}',
                  store_rejects = true,
                  rejects_table = '{errors}',
                  rejects_scan  = '{scans}'
                )
            """)
            stage_tables.append(stage)

        union_sql = " UNION ALL BY NAME ".join(
            f"SELECT * FROM {t}" for t in stage_tables)
        con.execute(f"CREATE OR REPLACE TABLE {feed} AS {union_sql}")
    finally:
        for t in stage_tables:
            con.execute(f"DROP TABLE IF EXISTS {t}")

    rows_loaded = con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0]
    return FeedHealth.of(feed, rows_loaded, len(rejects(con, feed)),
                         _unmatched(con, feed), _null_critical(con, feed))


def load_all(con: duckdb.DuckDBPyConnection, source) -> dict[str, FeedHealth]:
    """Load order matters: the referential checks read trips and feedback, so
    those must exist first. Two passes rather than one clever ordering.

    Each feed is loaded raw (via load_feed, unchanged), renamed to `<feed>_raw`,
    and replaced at the name `<feed>` by its NORMALISE view -- so every table
    load_feed touches is used exactly as written, and normalisation is purely
    additive on top. The rename+view pair is idempotent (guarded by DROP ... IF
    EXISTS) so load_all can run twice on the same connection.
    """
    for feed in FEEDS:
        con.execute(f"DROP VIEW IF EXISTS {feed}")
        con.execute(f"DROP TABLE IF EXISTS {feed}_raw")
        load_feed(con, feed, source(feed))
        con.execute(f"ALTER TABLE {feed} RENAME TO {feed}_raw")
        if feed in NORMALISE:
            con.execute(NORMALISE[feed])
    # Second pass: recompute health now that every table exists AND every feed
    # is normalised, so the referential counts are real rather than
    # zero-because-absent or ~100%-because-the-three-id-formats-never-compare-equal.
    return {feed: FeedHealth.of(feed,
                                con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0],
                                len(rejects(con, feed)),
                                _unmatched(con, feed),
                                _null_critical(con, feed))
            for feed in FEEDS}


def rejects(con: duckdb.DuckDBPyConnection, feed: str) -> list[dict]:
    """A quarantined row is a finding, not a log line."""
    table = f"reject_errors_{feed}"
    try:
        rows = con.sql(f"""
            SELECT line, coalesce(column_name, '') AS column_name,
                   coalesce(error_message, '') AS error_message,
                   coalesce(csv_line, '') AS csv_line
            FROM {table}
        """).fetchall()
    except duckdb.CatalogException:
        return []   # DuckDB only creates the table when there is a reject
    return [{"line": r[0], "column": r[1], "error": r[2], "raw": r[3]} for r in rows]


def _present_columns(con, table: str) -> set[str]:
    return {r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()}


def _unmatched(con, feed: str) -> int:
    sql = UNMATCHED_SQL.get(feed)
    if not sql:
        return 0
    try:
        return con.sql(sql).fetchone()[0]
    except duckdb.Error:
        return 0    # a referenced table not loaded yet; the second pass fixes it


def _null_critical(con, feed: str) -> int:
    cols = CRITICAL.get(feed, ())
    if not cols:
        return 0
    present = _present_columns(con, feed)
    missing = [c for c in cols if c not in present]
    rows = con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0]
    if missing:
        # A critical column absent from the dataset entirely: every row is
        # critically incomplete, and the confidence figure should say so.
        return rows
    predicate = " OR ".join(f"{c} IS NULL" for c in cols)
    return con.sql(f"SELECT count(*) FROM {feed} WHERE {predicate}").fetchone()[0]
