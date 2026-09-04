#!/usr/bin/env python3
"""Carve a small, deterministic, join-consistent slice out of the real dataset.

Replaces the synthetic fixture, which was built to a guessed schema (six feeds,
epoch milliseconds, an invented night_escort column) and would have pinned the
WRONG contract in every test.

Three properties this has to have, and the third is the one that is easy to get
wrong:

  1. SMALL enough to commit (~2-3 MB) so the suite runs offline and fast.
  2. DETERMINISTIC -- a contiguous slice by row order, no sampling, no seed.
  3. JOIN-CONSISTENT -- the other four feeds are filtered to the SAME trip_ids
     as the trips slice. A naive `head -n` on each file independently gives you
     five slices that share almost no trip_ids, every join returns zero rows,
     and the tests pass while asserting nothing.

Every column is read and written as VARCHAR so the real quirks survive intact:
comma-formatted trip_ids and epochs, the four date formats, the stray "False" in
severity, negative distances, dtype drift. Those quirks ARE the test material.

Usage:  service/.venv/bin/python scripts/make_sample.py [n_trips]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb

REAL = Path("data/real")
OUT = Path("data/sample")
N_TRIPS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000

# (feed, source glob, the column holding trip_id in that file)
FEEDS = [
    ("trips", "Ride_data*trip-*.csv", "trip_id"),
    ("emp_legs", "emp_Data.csv", "trip_id"),
    ("feedback", "trip_feedback.csv", "trip_id"),
    ("bill", "bill_data.csv", "trip_id"),
    ("alerts", "alerts_data.csv", "trip_id"),
]

# trip_id is comma-formatted in trips/feedback/alerts, a plain numeric string in
# bill, and int64 in emp_legs. This is the normalisation every join needs.
#
# TRY_CAST, not CAST: bill_data.trip_id holds the literal string 'OverHead' on
# 160 rows -- vendor overhead charges not tied to any trip. A hard CAST dies on
# them. Not mentioned in the dictionary; found by hitting it.
KEY = "TRY_CAST(REPLACE(CAST({col} AS VARCHAR), ',', '') AS BIGINT)"


def main() -> None:
    if not REAL.is_dir():
        sys.exit(f"no dataset at {REAL} -- run scripts/fetch-dataset.sh first")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = true")

    trips_glob = str(REAL / "Ride_data*trip-*.csv")

    # STRATIFIED, not the first N. trip_id is sequential, so taking the lowest
    # ids gave one business unit, five vendors, early May only, and almost no
    # quirks -- a sample that would have made every test look fine while
    # covering nothing. Taking every Nth id across the whole ordered set keeps
    # all five tenants, all 23 vendors, all three months and the quirk
    # distribution, and is still fully deterministic with no seed.
    con.execute(f"""
        CREATE TABLE trip_keys AS
        WITH all_keys AS (
          SELECT DISTINCT {KEY.format(col='trip_id')} AS k
          FROM read_csv_auto('{trips_glob}', all_varchar = true, union_by_name = true)
          WHERE {KEY.format(col='trip_id')} IS NOT NULL
        ), numbered AS (
          SELECT k, row_number() OVER (ORDER BY k) AS rn, count(*) OVER () AS total
          FROM all_keys
        )
        SELECT k FROM numbered
        WHERE rn % greatest(1, CAST(total / {N_TRIPS} AS BIGINT)) = 0
    """)
    n = con.sql("SELECT count(*) FROM trip_keys").fetchone()[0]
    print(f"selected {n} trip_ids -- every Nth across the full range, deterministic")

    total = 0
    for feed, glob, col in FEEDS:
        src = str(REAL / glob)
        dst = OUT / f"{feed}.csv"
        # Keep a few non-joinable rows on purpose. bill_data's 'OverHead' lines
        # are real money (Rs 44.6 lakh across 160 rows) that belongs to no trip,
        # and the ingest tests need them present to prove they are handled
        # rather than silently dropped.
        joinable = f"""
            SELECT s.* FROM read_csv_auto('{src}', all_varchar = true,
                                          union_by_name = true) s
            WHERE {KEY.format(col='s.' + col)} IN (SELECT k FROM trip_keys)
        """
        # Force-include rare rows the stratified slice would otherwise miss.
        # Each goes in its OWN subquery with its own LIMIT -- a trailing LIMIT on
        # a UNION applies to the whole result, which silently truncated bill to
        # 20 rows on the previous run.
        forced = {
            # 160 'OverHead' rows: Rs 44.6 lakh of vendor charges belonging to NO
            # trip. "Handled rather than silently dropped" is what the tests prove.
            "bill": "s.trip_id = 'OverHead'",
            # planned_km/traveled_km go to -6.63, which is physically impossible.
            # Too rare for a 0.5% slice to catch by chance.
            "emp_legs": "TRY_CAST(s.traveled_km AS DOUBLE) < 0 "
                        "OR TRY_CAST(s.planned_km AS DOUBLE) < 0",
            # severity carries a stray literal "False" outside its enum.
            "alerts": "s.severity = 'False'",
        }
        if feed in forced:
            joinable = f"""
            SELECT * FROM ({joinable})
            UNION ALL BY NAME
            SELECT * FROM (
              SELECT s.* FROM read_csv_auto('{src}', all_varchar = true,
                                            union_by_name = true) s
              WHERE {forced[feed]}
              LIMIT 25
            )
            """
        con.execute(f"COPY ({joinable}) TO '{dst}' (FORMAT CSV, HEADER, QUOTE '\"')")
        rows = con.sql(f"SELECT count(*) FROM read_csv_auto('{dst}', all_varchar=true)").fetchone()[0]
        size = dst.stat().st_size
        total += size
        print(f"  {feed:<10} {rows:>7,} rows  {size/1e6:>6.2f} MB")

    print(f"\ntotal {total/1e6:.2f} MB")

    # The property that makes this worth doing: the joins actually resolve.
    joined = con.sql(f"""
        SELECT count(*) FROM
          read_csv_auto('{OUT}/trips.csv', all_varchar=true) t
          JOIN read_csv_auto('{OUT}/bill.csv', all_varchar=true) b
            ON {KEY.format(col='t.trip_id')} = {KEY.format(col='b.trip_id')}
    """).fetchone()[0]
    print(f"trips JOIN bill on the normalised key: {joined:,} rows")
    if joined == 0:
        sys.exit("FAIL: joins return nothing -- the slice is not join-consistent")

    # And that the quirks survived, because they are the test material.
    print("\nquirks preserved (these are what the ingest tests assert on):")
    checks = [
        ("comma-formatted trip_id in trips", f"SELECT count(*) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true) WHERE trip_id LIKE '%,%'"),
        ("comma-formatted epochs in trips", f"SELECT count(*) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true) WHERE planned_start_epoch LIKE '%,%'"),
        ("plain (no-comma) trip_id in bill", f"SELECT count(*) FROM read_csv_auto('{OUT}/bill.csv', all_varchar=true) WHERE trip_id NOT LIKE '%,%'"),
        ("negative traveled_km in emp_legs", f"SELECT count(*) FROM read_csv_auto('{OUT}/emp_legs.csv', all_varchar=true) WHERE TRY_CAST(traveled_km AS DOUBLE) < 0"),
        ("stwid = 0 placeholders", f"SELECT count(*) FROM read_csv_auto('{OUT}/emp_legs.csv', all_varchar=true) WHERE stwid = '0'"),
        ("delay_reason values present", f"SELECT count(DISTINCT delay_reason) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("business_units present", f"SELECT count(DISTINCT business_unit) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("'OverHead' rows kept in bill", f"SELECT count(*) FROM read_csv_auto('{OUT}/bill.csv', all_varchar=true) WHERE trip_id = 'OverHead'"),
        ("literal 'null' strings in slab_name", f"SELECT count(*) FROM read_csv_auto('{OUT}/bill.csv', all_varchar=true) WHERE slab_name = 'null'"),
        ("vendors present", f"SELECT count(DISTINCT vendor_id) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("offices present", f"SELECT count(DISTINCT office) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("distinct trip_dates (months covered)", f"SELECT count(DISTINCT trip_date) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("product_types present", f"SELECT count(DISTINCT product_type) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true)"),
        ("alert event_types present", f"SELECT count(DISTINCT event_type) FROM read_csv_auto('{OUT}/alerts.csv', all_varchar=true)"),
        ("escort=true trips", f"SELECT count(*) FROM read_csv_auto('{OUT}/trips.csv', all_varchar=true) WHERE lower(actual_escort)='true'"),
        ("stray 'False' severity in alerts", f"SELECT count(*) FROM read_csv_auto('{OUT}/alerts.csv', all_varchar=true) WHERE severity='False'"),
    ]
    for label, q in checks:
        try:
            print(f"  {label:<38} {con.sql(q).fetchone()[0]:>7,}")
        except duckdb.Error as e:
            print(f"  {label:<38} n/a ({str(e)[:40]})")


if __name__ == "__main__":
    main()
