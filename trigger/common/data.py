"""One DuckDB connection with every feed loaded, shared by both agents.

Loading is NOT reimplemented: `signaldesk.ingest.load_all` is the
repository's own tolerant loader, and it is what normalises the three
different trip_id formats, converts epoch seconds to milliseconds and
buckets `shift_type` into EARLY/DAY/EVENING/NIGHT.

`ops_view` adds ONE view on top for the Team Manager: the normalised `trips`
view deliberately does not carry `actual_start_epoch` (the shift-planning
metrics never needed it), but "did the driver start late" cannot be answered
without it. The column is read from `trips_raw`, which ingest leaves behind,
and joined back -- an addition in our own connection, not a change to
anything under service/.

Both sides are collapsed to ONE ROW PER trip_id first. The sample carries 39
trip_ids on more than one row, and a plain join fans those out -- which does
not merely duplicate a ride in the output, it pairs one row's schedule with
another row's actual start and manufactures delays that never happened.
"""
from __future__ import annotations

import duckdb

from . import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from signaldesk import ingest


def connect(data_dir: str) -> tuple[duckdb.DuckDBPyConnection, dict]:
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


def ops_view(con: duckdb.DuckDBPyConnection) -> None:
    """`trip_ops`: the normalised trips view plus actual_start_epoch.

    Same TRY_CAST-and-strip-commas treatment ingest gives every other id and
    number, for the same reason: one malformed value must degrade a row, not
    abort the load.
    """
    con.execute("""
        CREATE OR REPLACE VIEW trip_ops AS
        WITH raw AS (
            SELECT TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
                   max(TRY_CAST(REPLACE(CAST(actual_start_epoch AS VARCHAR), ',', '')
                                AS BIGINT)) * 1000 AS actual_start_at,
                   max(route_source)             AS route_source,
                   max(actual_cab_registration)  AS actual_cab_registration,
                   max(planned_cab_registration) AS planned_cab_registration
            FROM trips_raw
            GROUP BY 1
        ), one_row_per_trip AS (
            SELECT * FROM trips
            QUALIFY row_number() OVER (PARTITION BY trip_id ORDER BY scheduled_at) = 1
        )
        SELECT t.*, r.actual_start_at, r.route_source,
               r.actual_cab_registration, r.planned_cab_registration
        FROM one_row_per_trip t
        LEFT JOIN raw r USING (trip_id)
    """)
