#!/usr/bin/env python3
"""Task 17 -- synthetic augmentation datasets for delay REASONING.

============================================================================
INTEGRITY RULE -- READ BEFORE TOUCHING THIS FILE.

Everything this script writes is SYNTHETIC. It is generated to demonstrate a
reasoning capability the PROVIDED dataset cannot support on its own: whether
a trip's delay is attributable to the commuter (was the OTP verified late
against the planned pickup?), to traffic (was the corridor congested?), or
to the driver/vendor (MoveInSync's own real `delay_reason` label). None of
the three real feeds carry an OTP timestamp, a traffic-congestion proxy, or
an ETA-revision history -- this script invents all three, on top of REAL
trip_id/stwid keys so the joins are meaningful, but the VALUES are fabricated.

Nothing generated here may ever be presented as, mixed into, or loaded
alongside the provided dataset as though it were provided data:

  1. It lives ONLY under data/synthetic/ -- a folder of its own, never inside
     data/real/ or data/sample/. This script only READS those two (read-only,
     to draw real trip_id/stwid keys and real delay_reason labels); it never
     writes into either.
  2. Every row of every file carries a `source` column whose value is the
     literal string 'SYNTHETIC'.
  3. service/signaldesk/ingest.py loads these files ONLY when the
     SIGNALDESK_SYNTHETIC=1 environment variable is set (default OFF), and
     only if data/synthetic/ actually exists -- a missing folder or an unset
     flag is a silent no-op, never an error. When loaded, every feed-health
     entry is named `*_synthetic` (otp_synthetic/traffic_synthetic/
     eta_synthetic) and every finding derived from these feeds carries
     `synthetic: true` in its JSON, so the console can badge it rather than
     silently blending it into the graded, provided-data findings.

If you are re-reading this rule from data/synthetic/README.md instead: it is
the same rule, in the same words, deliberately kept in both places.
============================================================================

Produces three CSVs, each capped at --cap rows (default 200,000) so the repo
stays sane even if a future run points --source at the full real dataset:

  otp_events.csv    -- one row per employee leg that BOARDED (is_no_show is
                       real-data FALSE), the synthetic OTP-verification story:
                       trip_id, stwid, planned_pickup_epoch, otp_sent_epoch,
                       otp_verified_epoch, verification_attempts, source.
                       otp_verified_epoch - planned_pickup_epoch is the
                       COMMUTER-CAUSED boarding delay this file exists to
                       synthesize -- drawn from a mixture (~70% within +/-2
                       min, ~20% 3-10 min, ~10% 11-30 min) that shifts toward
                       the slow tail (~40/30/30) whenever the trip's REAL
                       delay_reason is 'EMPLOYEE', so the synthetic story
                       agrees with MoveInSync's own label instead of being
                       drawn independently of it.

  traffic_index.csv -- one row per site x shift_band x day actually observed
                       in the real trips: site_id, shift_band, date,
                       corridor_congestion_index (0-100), avg_speed_kmph,
                       source. The index correlates with that site/band/day's
                       REAL delay_reason='TRAFFIC' share, plus noise; speed is
                       the (noisy) inverse of the index.

  eta_log.csv       -- one row per trip (deterministically sampled if the
                       source has more trips than --cap): trip_id,
                       eta_at_dispatch_epoch, eta_revised_epoch, revisions,
                       final_eta_epoch, source. The ETA drifts from an
                       initial guess near the PLANNED end time toward the
                       REAL actual end time, with more revisions on trips the
                       real data marks delayed (delay_reason not NODELAY).

All three keep the raw epoch columns in SECONDS, matching the real dataset's
own convention (docs/real-dataset-mapping.md SS2) -- ingest.py's own
NORMALISE step is what converts to epoch milliseconds, exactly as it already
does for every real feed.

Everything here is SEEDED and DETERMINISTIC: a fixed `random.Random(seed)`
instance is advanced in one fixed row order (by trip_id, then stwid where
applicable), so the same --seed against the same --source always produces
byte-identical output. No wall-clock, no OS randomness, no dict-iteration-
order dependency.

Usage:
    service/.venv/bin/python scripts/make_synthetic.py \\
        --seed 20260905 --source data/real --out data/synthetic
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import duckdb

SEED_DEFAULT = 20260905
CAP_DEFAULT = 200_000
SOURCE_DEFAULT = "data/real"
OUT_DEFAULT = "data/synthetic"

# Mirrors ingest.py's own on-time grace (constants.ON_TIME_GRACE_MS = 5 min)
# -- kept as a plain literal here rather than importing service.signaldesk,
# so this script has zero dependency on the service package and can run
# standalone exactly like scripts/make_sample.py.
GRACE_S = 5 * 60

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Source resolution -- mirrors ingest.py's source_for()/GLOBS, standalone.
# data/sample/ uses a plain "<feed>.csv"; data/real/ uses the real filenames
# (a monthly glob for trips, and a differently-cased single file for legs).
# ---------------------------------------------------------------------------

def _trips_glob(base: Path) -> str:
    plain = base / "trips.csv"
    if plain.exists():
        return str(plain)
    return str(base / "Ride_data*trip-*.csv")


def _emp_legs_path(base: Path) -> str:
    plain = base / "emp_legs.csv"
    if plain.exists():
        return str(plain)
    return str(base / "emp_Data.csv")


def resolve_source(requested: Path) -> Path:
    """--source data/real if it exists and has trip data; otherwise fall
    back to data/sample and SAY SO on stdout, per the task's own instruction
    ("if data/real/ is absent fall back to data/sample/ and say so")."""
    has_trips = requested.is_dir() and (
        (requested / "trips.csv").exists()
        or any(requested.glob("Ride_data*trip-*.csv"))
    )
    if has_trips:
        return requested
    fallback = REPO_ROOT / "data" / "sample"
    print(f"no dataset at {requested} -- falling back to {fallback}")
    if not fallback.is_dir():
        sys.exit(f"FAIL: fallback {fallback} does not exist either")
    return fallback


# ---------------------------------------------------------------------------
# Deterministic per-row synthesis. A single random.Random(seed) is threaded
# through every draw below, consumed in one fixed row order per file, so a
# re-run with the same --seed is byte-identical.
# ---------------------------------------------------------------------------

def _draw_otp(rng: random.Random, is_employee_reason: bool) -> tuple[float, int]:
    """(delay_seconds, verification_attempts). delay_seconds is
    otp_verified_epoch - planned_pickup_epoch -- the commuter-caused
    boarding delay. Mixture ~70/20/10 (within 2min / 3-10min / 11-30min)
    ordinarily; shifted to ~40/30/30 when the trip's REAL delay_reason is
    'EMPLOYEE', so the tail agrees with MoveInSync's own label."""
    weights = (0.40, 0.30, 0.30) if is_employee_reason else (0.70, 0.20, 0.10)
    bucket = rng.choices((0, 1, 2), weights=weights, k=1)[0]
    if bucket == 0:
        return rng.uniform(-120.0, 120.0), 1
    if bucket == 1:
        return rng.uniform(180.0, 600.0), rng.randint(1, 2)
    return rng.uniform(660.0, 1800.0), rng.randint(2, 4)


def _draw_traffic(rng: random.Random, traffic_share: float) -> tuple[float, float]:
    """(corridor_congestion_index, avg_speed_kmph). The index correlates
    with this site/band/day's REAL TRAFFIC delay-reason share, plus Gaussian
    noise; speed is the noisy inverse of the index."""
    idx = 12.0 + 70.0 * traffic_share + rng.gauss(0.0, 6.0)
    idx = min(100.0, max(0.0, idx))
    speed = 55.0 - 0.42 * idx + rng.gauss(0.0, 3.0)
    speed = min(65.0, max(6.0, speed))
    return round(idx, 1), round(speed, 1)


def _draw_eta(rng: random.Random, planned_start: float, planned_end: float,
             actual_end: float, delayed: bool, delay_minutes: float | None
             ) -> tuple[int, int, int, int]:
    """(eta_at_dispatch_epoch, eta_revised_epoch, revisions, final_eta_epoch).
    The ETA drifts from an initial guess near the PLANNED end time toward the
    REAL actual end time; `revisions` is higher on trips the real data marks
    delayed (delay_reason not NODELAY), with an extra bump for a larger
    delay_minutes."""
    duration = max(planned_end - planned_start, 60.0)
    eta_dispatch = planned_end + rng.uniform(-0.05, 0.05) * duration

    if delayed:
        bump = 2 if (delay_minutes or 0) > 60 else (1 if (delay_minutes or 0) > 15 else 0)
        revisions = min(rng.randint(2, 6) + bump, 10)
    else:
        revisions = rng.randint(0, 2)

    # More revisions -> tighter final convergence toward the real actual end.
    residual_scale = max(30.0, 180.0 / (1 + revisions))
    final_eta = actual_end + rng.uniform(-residual_scale, residual_scale)

    frac = 0.5 + rng.uniform(-0.15, 0.15)
    eta_revised = eta_dispatch + frac * (final_eta - eta_dispatch)

    return round(eta_dispatch), round(eta_revised), revisions, round(final_eta)


# ---------------------------------------------------------------------------
# Deterministic capping -- identical technique to scripts/make_sample.py's
# own trip_keys sample: row_number() over a fixed order, keep every Nth row.
# total <= cap collapses the modulo to 1 (keep everything).
# ---------------------------------------------------------------------------

def _capped(con: duckdb.DuckDBPyConnection, select_sql: str, order_by: str, cap: int) -> str:
    return f"""
        WITH numbered AS (
          SELECT *, row_number() OVER (ORDER BY {order_by}) AS __rn,
                 count(*) OVER () AS __total
          FROM ({select_sql}) s
        )
        SELECT * EXCLUDE (__rn, __total) FROM numbered
        WHERE __rn % greatest(1, CAST(__total / {cap} AS BIGINT)) = 0
    """


def _write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate(source: Path, out: Path, seed: int, cap: int = CAP_DEFAULT) -> dict:
    """Runs the full generation and returns a stats dict (used both by
    main()'s printed report and by data/synthetic/README.md's own numbers).
    Deterministic and side-effect-free beyond writing the three CSVs (and
    README.md) under `out` -- never touches `source`."""
    source = resolve_source(source)
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = true")

    trips_glob = _trips_glob(source)
    emp_glob = _emp_legs_path(source)

    # trip_id is comma-formatted in the real ride_data_trip; a clean int64 in
    # emp_data. Same normalisation as ingest.py/make_sample.py.
    con.execute(f"""
        CREATE OR REPLACE TABLE trips_norm AS
        SELECT
          TRY_CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          office AS site_id,
          CASE
            WHEN TRY_CAST(split_part(shift_type, ':', 1) AS INTEGER) BETWEEN 4 AND 7   THEN 'EARLY'
            WHEN TRY_CAST(split_part(shift_type, ':', 1) AS INTEGER) BETWEEN 8 AND 15  THEN 'DAY'
            WHEN TRY_CAST(split_part(shift_type, ':', 1) AS INTEGER) BETWEEN 16 AND 21 THEN 'EVENING'
            WHEN TRY_CAST(split_part(shift_type, ':', 1) AS INTEGER) IS NOT NULL       THEN 'NIGHT'
            ELSE NULL
          END AS shift_band,
          TRY_CAST(STRPTIME(trip_date, '%B %d, %Y') AS DATE) AS trip_date,
          delay_reason,
          TRY_CAST(REPLACE(CAST(delay_minutes AS VARCHAR), ',', '') AS DOUBLE) AS delay_minutes,
          TRY_CAST(REPLACE(CAST(planned_start_epoch AS VARCHAR), ',', '') AS DOUBLE) AS planned_start_epoch,
          TRY_CAST(REPLACE(CAST(planned_end_epoch AS VARCHAR), ',', '') AS DOUBLE) AS planned_end_epoch,
          TRY_CAST(REPLACE(CAST(actual_end_epoch AS VARCHAR), ',', '') AS DOUBLE) AS actual_end_epoch
        FROM read_csv_auto('{trips_glob}', all_varchar = true, union_by_name = true)
    """)
    (real_trip_rows,) = con.sql("SELECT count(*) FROM trips_norm").fetchone()

    # trip_id is NOT globally unique in the real ride_data_trip feed -- the
    # same id is reused across the three monthly files for two otherwise-
    # unrelated trips (measured: 615,546 real trip rows, 608,793 distinct
    # trip_ids). Joining emp_norm to trips_norm directly on trip_id would
    # FAN OUT on every reused id (one employee leg producing two otp_events
    # rows, nondeterministically ordered between runs) -- deduping to one
    # deterministically-chosen delay_reason per trip_id first (the row with
    # the smallest planned_start_epoch; (trip_id, planned_start_epoch) is
    # verified globally unique, so the tie-break is never ambiguous) is what
    # this table is for.
    con.execute("""
        CREATE OR REPLACE TABLE trips_delay AS
        SELECT trip_id, arg_min(delay_reason, planned_start_epoch) AS delay_reason
        FROM trips_norm
        WHERE trip_id IS NOT NULL
        GROUP BY trip_id
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE emp_norm AS
        SELECT
          TRY_CAST(trip_id AS BIGINT) AS trip_id,
          TRY_CAST(stwid AS BIGINT) AS stwid,
          TRY_CAST(planned_pickup_epoch AS DOUBLE) AS planned_pickup_epoch,
          lower(is_no_show) = 'false' AS boarded
        FROM read_csv_auto('{emp_glob}', all_varchar = true)
    """)
    (real_emp_rows,) = con.sql("SELECT count(*) FROM emp_norm").fetchone()

    stats: dict = {
        "seed": seed, "cap": cap, "source": str(source), "out": str(out),
        "real_trip_rows": int(real_trip_rows), "real_emp_rows": int(real_emp_rows),
    }

    # -- otp_events.csv --------------------------------------------------
    # stwid = 0 is a placeholder (not a real employee) per
    # data/real/Dictionary/emp_data.md -- excluded here for the same reason
    # ingest.py's own emp_legs NORMALISE view excludes it, and because a
    # handful of trip_id/stwid=0 pairs repeat (multiple placeholder rows per
    # trip), which would otherwise make the ORDER BY below tie-break
    # nondeterministically between runs.
    boarded_sql = """
        SELECT e.trip_id, e.stwid, e.planned_pickup_epoch,
               t.delay_reason
        FROM emp_norm e
        LEFT JOIN trips_delay t ON t.trip_id = e.trip_id
        WHERE e.boarded AND e.planned_pickup_epoch IS NOT NULL AND e.stwid <> 0
    """
    (boarded_eligible,) = con.sql(f"SELECT count(*) FROM ({boarded_sql}) s").fetchone()
    stats["boarded_legs_eligible"] = int(boarded_eligible)
    # order by the PROJECTED column names (trip_id, stwid), not the aliased
    # e.trip_id/e.stwid from the inner select -- _capped() wraps boarded_sql
    # in an outer `numbered` select that only sees the projection.
    capped_sql = _capped(con, boarded_sql, "trip_id, stwid", cap)
    rows = con.execute(capped_sql).fetchall()

    rng = random.Random(seed)
    otp_rows = []
    n_employee_reason = 0
    for trip_id, stwid, planned_pickup_epoch, delay_reason in sorted(
            rows, key=lambda r: (r[0], r[1])):
        is_employee = delay_reason == "EMPLOYEE"
        n_employee_reason += is_employee
        delay_s, attempts = _draw_otp(rng, is_employee)
        otp_sent = planned_pickup_epoch
        otp_verified = planned_pickup_epoch + delay_s
        otp_rows.append((
            trip_id, stwid, planned_pickup_epoch,
            round(otp_sent), round(otp_verified), attempts, "SYNTHETIC",
        ))
    otp_rows.sort(key=lambda r: (r[0], r[1]))
    _write_csv(out / "otp_events.csv",
              ["trip_id", "stwid", "planned_pickup_epoch", "otp_sent_epoch",
               "otp_verified_epoch", "verification_attempts", "source"],
              otp_rows)
    stats["otp_events_rows"] = len(otp_rows)
    stats["otp_events_employee_labeled"] = n_employee_reason

    # -- traffic_index.csv ------------------------------------------------
    # Naturally small (site x shift_band x day actually observed) -- rarely
    # anywhere near --cap in production, but a small --cap (as tests use, for
    # a fast tiny fixture) CAN exceed the natural population, so this goes
    # through the same deterministic every-Nth-row capping as the other two
    # files rather than a plain truncation (which would keep only the
    # alphabetically-first sites and silently bias the sample).
    traffic_agg_sql = """
        SELECT site_id, shift_band, trip_date AS date, count(*) AS n,
               sum(CASE WHEN delay_reason = 'TRAFFIC' THEN 1 ELSE 0 END) AS traffic_n
        FROM trips_norm
        WHERE site_id IS NOT NULL AND shift_band IS NOT NULL AND trip_date IS NOT NULL
        GROUP BY site_id, shift_band, trip_date
    """
    capped_traffic_sql = _capped(con, traffic_agg_sql, "site_id, shift_band, date", cap)
    traffic_agg = con.execute(capped_traffic_sql).fetchall()

    rng_traffic = random.Random(seed + 1)  # independent stream from otp_events
    traffic_rows = []
    for site_id, shift_band, date, n, traffic_n in sorted(
            traffic_agg, key=lambda r: (r[0], r[1], r[2])):
        share = traffic_n / n if n else 0.0
        idx, speed = _draw_traffic(rng_traffic, share)
        traffic_rows.append((site_id, shift_band, date.isoformat(), idx, speed, "SYNTHETIC"))
    _write_csv(out / "traffic_index.csv",
              ["site_id", "shift_band", "date", "corridor_congestion_index",
               "avg_speed_kmph", "source"],
              traffic_rows)
    stats["traffic_index_rows"] = len(traffic_rows)

    # -- eta_log.csv --------------------------------------------------------
    eta_source_sql = """
        SELECT trip_id, planned_start_epoch, planned_end_epoch, actual_end_epoch,
               delay_reason, delay_minutes
        FROM trips_norm
        WHERE trip_id IS NOT NULL AND planned_start_epoch IS NOT NULL
          AND planned_end_epoch IS NOT NULL AND actual_end_epoch IS NOT NULL
    """
    (eta_eligible,) = con.sql(f"SELECT count(*) FROM ({eta_source_sql}) s").fetchone()
    stats["eta_trips_eligible"] = int(eta_eligible)
    # trip_id is NOT globally unique in the real ride_data_trip feed (it is
    # reused across the three monthly files -- e.g. trip_id 1210469 names two
    # entirely different trips, one in May and one in July); ORDER BY
    # trip_id alone leaves row_number()'s tie-break among duplicates
    # unspecified (and DuckDB is not guaranteed stable there), so
    # planned_start_epoch is added as a tiebreak -- verified unique per
    # (trip_id, planned_start_epoch) pair across the whole real dataset.
    capped_eta_sql = _capped(con, eta_source_sql, "trip_id, planned_start_epoch", cap)
    eta_source_rows = con.execute(capped_eta_sql).fetchall()

    rng_eta = random.Random(seed + 2)  # independent stream
    eta_rows = []
    for trip_id, planned_start, planned_end, actual_end, delay_reason, delay_minutes in sorted(
            eta_source_rows, key=lambda r: r[0]):
        delayed = delay_reason is None or delay_reason != "NODELAY"
        eta_dispatch, eta_revised, revisions, final_eta = _draw_eta(
            rng_eta, planned_start, planned_end, actual_end, delayed, delay_minutes)
        eta_rows.append((trip_id, eta_dispatch, eta_revised, revisions, final_eta, "SYNTHETIC"))
    eta_rows.sort(key=lambda r: r[0])
    _write_csv(out / "eta_log.csv",
              ["trip_id", "eta_at_dispatch_epoch", "eta_revised_epoch", "revisions",
               "final_eta_epoch", "source"],
              eta_rows)
    stats["eta_log_rows"] = len(eta_rows)

    _write_readme(out, stats)
    return stats


README_TEMPLATE = """# data/synthetic/ -- augmentation datasets for delay reasoning (Task 17)

**Synthetic. Generated to demonstrate reasoning the provided dataset cannot
support -- never presented as provided data.**

This folder is separate from `data/real/` and `data/sample/` on purpose --
see the integrity rule at the top of `scripts/make_synthetic.py`, repeated
here:

  1. Every row of every file below carries `source = 'SYNTHETIC'`.
  2. `service/signaldesk/ingest.py` loads these files ONLY when
     `SIGNALDESK_SYNTHETIC=1` (default OFF) and this folder exists -- a
     missing folder or an unset flag is a silent no-op, never an error.
  3. When loaded, every feed-health entry is named `otp_synthetic` /
     `traffic_synthetic` / `eta_synthetic`, and every finding derived from
     these feeds carries `synthetic: true` in its JSON response
     (`GET /api/findings/{{id}}/attribution`), so the console can badge it.

Regenerate with the exact command that produced this run:

    service/.venv/bin/python scripts/make_synthetic.py \\
        --seed {seed} --source {source} --out {out} --cap {cap}

## Files

### otp_events.csv ({otp_events_rows:,} rows)

One row per employee leg that BOARDED (real `emp_data.is_no_show = False`):
`trip_id, stwid, planned_pickup_epoch, otp_sent_epoch, otp_verified_epoch,
verification_attempts, source`.

`otp_verified_epoch - planned_pickup_epoch` is the **commuter-caused boarding
delay** this file exists to synthesize. Drawn from a mixture --
~70% within +/-2 minutes, ~20% 3-10 minutes, ~10% 11-30 minutes -- **shifted to
~40/30/30 whenever the trip's REAL `delay_reason` is `'EMPLOYEE'`**, so the
synthetic tail agrees with MoveInSync's own label instead of being drawn
independently of it. Of {otp_events_rows:,} generated rows, {otp_events_employee_labeled:,}
sit on a trip the real data itself already labels `EMPLOYEE`.

Source population: {real_emp_rows:,} real `emp_data` rows -> {boarded_legs_eligible:,}
boarded legs with a non-null planned pickup -> capped at ~{cap:,} rows
({otp_events_rows:,} actually written) via a deterministic every-Nth-row
sample ordered by (trip_id, stwid) (identical technique to
`scripts/make_sample.py`'s own trip_keys sample).

### traffic_index.csv ({traffic_index_rows:,} rows)

One row per (site, shift_band, day) actually observed in the real trips:
`site_id, shift_band, date, corridor_congestion_index (0-100), avg_speed_kmph,
source`.

`corridor_congestion_index` correlates with that site/band/day's REAL
`delay_reason = 'TRAFFIC'` share (`12 + 70 x share + noise`, clipped to
[0, 100]); `avg_speed_kmph` is the noisy inverse (`55 - 0.42 x index + noise`,
clipped to [6, 65]). Not sampled down -- every (site, shift_band, day)
combination present in the real trips gets a row, and that population is
naturally small (well under the {cap:,}-row cap).

### eta_log.csv ({eta_log_rows:,} rows -- NOT committed)

Generated by this script and used by any test that asks for it, but excluded
from the repo (`.gitignore`: `data/synthetic/eta_log.csv`) -- of the three
files, it is the least load-bearing for the attribution story (which runs on
OTP + traffic + the real `delay_reason`) and roughly doubles this folder's
weight. Regenerate it with the exact command above (same `--seed` -> the
byte-identical file) whenever a demo or a test needs it on disk.

One row per trip with a complete real planned/actual timing:
`trip_id, eta_at_dispatch_epoch, eta_revised_epoch, revisions,
final_eta_epoch, source`.

The ETA drifts from an initial guess near the REAL planned end time toward
the REAL actual end time (`final_eta_epoch` is `actual_end_epoch +/- noise`,
tighter the more it was revised). `revisions` is higher on trips the real
data marks delayed (`delay_reason` not `NODELAY`), with an extra bump for a
larger `delay_minutes`.

Inherited real-data quirk, not one this script introduces: `trip_id` is not
globally unique in `ride_data_trip` -- the same id is reused across the
three monthly files for two otherwise-unrelated trips (confirmed: 615,546
real trip rows, 608,793 distinct trip_ids). A `trip_id` can therefore name
two rows here too, distinguished by nothing this file carries -- join on the
full row content, or on `(trip_id, final_eta_epoch)`, when that matters.

Source population: {real_trip_rows:,} real trip rows -> {eta_trips_eligible:,} with a
complete planned start/end and actual end -> capped at ~{cap:,} rows
({eta_log_rows:,} actually written) via a deterministic every-Nth-row sample
ordered by trip_id.

## Seed and reproducibility

Seed: **{seed}**. Every random draw comes from `random.Random(seed)` (or
`seed+1`/`seed+2` for the traffic and ETA files, so the three files draw from
independent streams), consumed in one fixed row order per file -- the same
seed against the same `--source` always regenerates byte-identical CSVs.

## Epoch units

All `*_epoch` columns above are epoch **SECONDS**, matching the real
dataset's own convention (`docs/real-dataset-mapping.md` SS2) --
`ingest.py`'s NORMALISE step converts to epoch milliseconds at the ingest
boundary, exactly as it already does for every real feed.
"""


def _write_readme(out: Path, stats: dict) -> None:
    (out / "README.md").write_text(README_TEMPLATE.format(**stats))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    parser.add_argument("--source", type=str, default=SOURCE_DEFAULT)
    parser.add_argument("--out", type=str, default=OUT_DEFAULT)
    parser.add_argument("--cap", type=int, default=CAP_DEFAULT,
                        help="max rows per generated file (default 200,000); "
                             "tests pass a small value for a fast, tiny fixture")
    args = parser.parse_args()

    stats = generate(Path(args.source), Path(args.out), args.seed, args.cap)

    print(f"seed={stats['seed']} cap={stats['cap']}")
    print(f"source={stats['source']}")
    print(f"real trips scanned: {stats['real_trip_rows']:,}")
    print(f"real emp legs scanned: {stats['real_emp_rows']:,}")
    print(f"otp_events.csv: {stats['otp_events_rows']:,} rows "
         f"({stats['otp_events_employee_labeled']:,} on a real EMPLOYEE-labeled trip)")
    print(f"traffic_index.csv: {stats['traffic_index_rows']:,} rows")
    print(f"eta_log.csv: {stats['eta_log_rows']:,} rows")
    print(f"written to {stats['out']}/ (README.md included)")


if __name__ == "__main__":
    main()
