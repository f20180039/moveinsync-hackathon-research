import os
import pathlib

import duckdb
import pytest

from signaldesk import ingest


@pytest.fixture
def con():
    c = duckdb.connect()
    yield c
    c.close()


SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")


# ---------------------------------------------------------------------------
# Step 1 tests, from the brief, verbatim in intent.
# ---------------------------------------------------------------------------

def test_a_malformed_row_is_quarantined_and_counted_rather_than_dropped(con, tmp_path):
    (tmp_path / "trips.csv").write_text(
        "trip_id,vendor_id,scheduled_at\n"
        "T1,V01,100\n"
        "T2,V01,200,UNEXPECTED_EXTRA_FIELD\n"
        "T3,V02,300\n"
    )
    health = ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))

    assert health.rows_loaded == 2, "the two good rows survive"
    assert health.rows_rejected == 1, "the bad row is counted, not silently lost"
    assert len(ingest.rejects(con, "trips")) == 1
    assert ingest.rejects(con, "trips")[0]["line"] == 3


def test_union_by_name_merges_two_files_with_different_column_sets(con, tmp_path):
    (tmp_path / "trips_a.csv").write_text("trip_id,vendor_id\nT1,V01\n")
    (tmp_path / "trips_b.csv").write_text("trip_id,site_id\nT2,SITE1\n")

    ingest.load_feed(con, "trips", str(tmp_path / "trips_*.csv"))

    row = con.sql("SELECT count(*) n, count(vendor_id) v, count(site_id) s FROM trips").fetchone()
    assert row == (2, 1, 1)


def test_a_second_query_does_not_rescan_the_csv_or_double_count_rejects(con, tmp_path):
    # BUG F2. A lazy view over read_csv_auto(store_rejects=true) re-scans on every
    # query and re-appends to the rejects table. Every metric query would do that.
    (tmp_path / "trips.csv").write_text(
        "trip_id,vendor_id\nT1,V01\nT2,V01,EXTRA\n")
    health = ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))

    con.sql("SELECT count(*) FROM trips").fetchone()
    con.sql("SELECT count(*) FROM trips").fetchone()

    assert len(ingest.rejects(con, "trips")) == health.rows_rejected
    assert con.sql("SELECT count(*) FROM reject_errors_trips").fetchone()[0] == 1


def test_each_feed_keeps_its_own_rejects(con, tmp_path):
    # BUG F2, second half: one shared rejects table left only the last feed's rows.
    (tmp_path / "trips.csv").write_text("trip_id\nT1\nT2,EXTRA\n")
    (tmp_path / "costs.csv").write_text("trip_id,total_inr\nT1,300\nT2,310,EXTRA\n")

    ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))
    ingest.load_feed(con, "costs", str(tmp_path / "costs.csv"))

    assert len(ingest.rejects(con, "trips")) == 1, "not clobbered by the costs load"
    assert len(ingest.rejects(con, "costs")) == 1


def test_confidence_is_exactly_one_on_clean_input_and_falls_on_each_fault(con, tmp_path):
    from signaldesk.schemas import FeedHealth
    assert FeedHealth.of("costs", 2, 0, 0, 0).confidence == 1.0
    assert FeedHealth.of("costs", 2, 0, 1, 0).confidence == 0.5   # unmatched
    assert FeedHealth.of("costs", 1, 1, 0, 0).confidence == 0.5   # rejected
    assert FeedHealth.of("costs", 1, 0, 0, 1).confidence == 0.0   # null critical
    assert FeedHealth.of("costs", 1, 0, 5, 0).confidence == 0.0   # clamped, not negative


def test_no_call_uses_ignore_errors():
    # A grep-as-a-test: ignore_errors silently drops VALID rows, and no
    # behavioural test would catch a future edit adding it.
    src = pathlib.Path(ingest.__file__).read_text()
    assert "ignore_errors" not in src


# ---------------------------------------------------------------------------
# Step 3b tests: the three normalisations, against the committed sample data.
# ---------------------------------------------------------------------------

def test_trip_id_normalises_to_the_same_integer_from_all_three_source_formats(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    # trips: comma-formatted string source. bill: plain numeric string source.
    # emp_legs: clean int64 source. All three must land as the same BIGINT type
    # and the same value space, or every join across feeds returns zero rows.
    types = con.sql("""
        SELECT
          (SELECT column_type FROM (DESCRIBE trips)    WHERE column_name='trip_id'),
          (SELECT column_type FROM (DESCRIBE bill)     WHERE column_name='trip_id'),
          (SELECT column_type FROM (DESCRIBE emp_legs) WHERE column_name='trip_id')
    """).fetchone()
    assert types == ("BIGINT", "BIGINT", "BIGINT")


def test_joining_trips_to_bill_on_the_normalised_key_returns_more_than_zero_rows(con):
    # THE test that matters: un-normalised, every join silently returns nothing
    # and every metric reports a DATA_GAP, which looks exactly like an engine
    # bug and is not one.
    ingest.load_all(con, ingest.source_for(SAMPLE))
    n = con.sql("SELECT count(*) FROM trips t JOIN bill b ON b.trip_id = t.trip_id").fetchone()[0]
    assert n > 0


def test_epochs_come_out_in_milliseconds_not_seconds(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    # A 2026 epoch in SECONDS is ~1.78 billion; in MILLISECONDS it is ~1.78
    # trillion. Two independent columns, two feeds, both must have moved.
    trips_ms, legs_ms = con.sql("""
        SELECT
          (SELECT min(scheduled_at) FROM trips WHERE scheduled_at IS NOT NULL),
          (SELECT min(planned_pickup_at) FROM emp_legs WHERE planned_pickup_at IS NOT NULL)
    """).fetchone()
    assert trips_ms > 1_000_000_000_000
    assert legs_ms > 1_000_000_000_000


def test_a_negative_planned_km_becomes_null_rather_than_a_negative_average(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    row = con.sql("""
        SELECT min(planned_km), min(traveled_km) FROM emp_legs
    """).fetchone()
    assert row[0] is None or row[0] >= 0
    assert row[1] is None or row[1] >= 0
    # and the fault is not simply invisible: the raw table still has it, so the
    # normalisation is a deliberate NULLing, not an absence of the fault.
    raw_min = con.sql("SELECT min(traveled_km) FROM emp_legs_raw").fetchone()[0]
    assert raw_min < 0


def test_the_stray_false_severity_becomes_null_not_a_fourth_severity_level(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    values = {r[0] for r in con.sql(
        "SELECT DISTINCT severity FROM alerts").fetchall()}
    assert "False" not in values
    assert values <= {"Sev-1", "Sev-2", "Sev-3", None}


def test_stwid_zero_rows_are_excluded_from_emp_legs(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    assert con.sql("SELECT count(*) FROM emp_legs WHERE stwid = 0").fetchone()[0] == 0
    # and the raw feed really did have some, so this is exclusion, not absence
    assert con.sql("SELECT count(*) FROM emp_legs_raw WHERE stwid = 0").fetchone()[0] > 0


def test_bill_overhead_trip_id_becomes_null_instead_of_killing_the_load(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    # 'OverHead' rows are real vendor charges belonging to no trip -- they must
    # survive the load (TRY_CAST) as a null trip_id, not crash it (CAST).
    n = con.sql("SELECT count(*) FROM bill WHERE trip_id IS NULL").fetchone()[0]
    assert n > 0


def test_bill_slab_name_literal_null_string_becomes_a_real_null(con):
    ingest.load_all(con, ingest.source_for(SAMPLE))
    assert con.sql("SELECT count(*) FROM bill WHERE slab_name = 'null'").fetchone()[0] == 0
    assert con.sql("SELECT count(*) FROM bill WHERE slab_name IS NULL").fetchone()[0] > 0


# ---------------------------------------------------------------------------
# Step 5: point it at whatever dataset is configured and print what it found.
# ---------------------------------------------------------------------------

def test_the_configured_dataset_loads_and_its_health_is_printed(con):
    base = os.environ.get("SIGNALDESK_DATA", SAMPLE)
    if not pathlib.Path(base).is_dir():
        pytest.skip(f"no dataset at {base}")
    health = ingest.load_all(con, ingest.source_for(base))
    for h in health.values():
        print(f"MEASURED {h.feed} loaded={h.rows_loaded} rejected={h.rows_rejected} "
              f"unmatched={h.unmatched_keys} nullCritical={h.null_critical_fields} "
              f"confidence={h.confidence:.4f}")
    assert all(0.0 <= h.confidence <= 1.0 for h in health.values())
    assert health["trips"].rows_loaded > 0
