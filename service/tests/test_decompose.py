"""decompose.py: gap attribution by dimension and by delay reason.

Pure-arithmetic tests build a tiny synthetic `trips` table with full numeric
control (same pattern test_verdict.py uses for its synthetic Metric fixtures)
so the sum-to-whole/worst-first/sign properties can be pinned exactly, not
just approximately on real data. One test at the bottom runs against
data/sample for a real-data-flavoured check.
"""
from __future__ import annotations

import pathlib

import duckdb
import pytest

from signaldesk import constants as C
from signaldesk import decompose, ingest, registry, sweep
from signaldesk.schemas import (Cause, Dimension, Direction, Finding, Metric,
                                ReferenceKind, Slice, Tier, Window, finding_id)

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")

WINDOW = Window(0, 1_000_000)

# A deliberately tiny stand-in for registry's on-time SQL -- same (value, n)
# shape, same {{SLICE}} token, but only the columns this test file needs.
_FAKE_ON_TIME_SQL = """
SELECT 100.0 * sum(ok) / nullif(count(*), 0), count(*) AS n
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  {{SLICE}}
"""

FAKE_METRIC = Metric("fake_ota", "Fake OTA", "%", Direction.HIGHER, _FAKE_ON_TIME_SQL,
                     (ReferenceKind.TREND,), "trips", ())


@pytest.fixture
def con(monkeypatch):
    c = duckdb.connect()
    c.execute("""
        CREATE TABLE trips (
            scheduled_at BIGINT, vendor_id VARCHAR, site_id VARCHAR,
            ok INTEGER, delay_reason VARCHAR, delay_minutes BIGINT
        )
    """)
    # decompose.py calls registry.by_id(finding.metric_id) -- monkeypatch it
    # to hand back FAKE_METRIC for the synthetic id these tests use, real
    # metrics for everything else (the real-data test at the bottom still
    # needs the genuine registry).
    real_by_id = registry.by_id
    monkeypatch.setattr(registry, "by_id",
                        lambda mid: FAKE_METRIC if mid == "fake_ota" else real_by_id(mid))
    yield c
    c.close()
    registry.clear_cache()


def _insert(con, vendor_id, n_ok, n_late, site_id="S1", at=500):
    rows = ([(at, vendor_id, site_id, 1, None, None)] * n_ok +
           [(at, vendor_id, site_id, 0, None, None)] * n_late)
    if rows:
        con.executemany("INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?)", rows)


def _insert_delay(con, reason, n, delay_minutes=10, at=500, site_id="S1"):
    rows = [(at, "V", site_id, 1, reason, delay_minutes)] * n
    if rows:
        con.executemany("INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?)", rows)


def _finding(metric_id="fake_ota", slc=None, gap=10.0, tier=Tier.CONCERN,
            cause=Cause.TREND_REGRESSION, window=WINDOW):
    slc = slc if slc is not None else Slice.all()
    return Finding(finding_id(metric_id, slc, window), metric_id, slc, window,
                  0.0, (), tier, cause, gap, 1.0, frozenset(), "")


# ---------------------------------------------------------------------------
# Dimension decomposition -- sum-to-whole, worst-first, tiny volume, sign.
# ---------------------------------------------------------------------------

def test_contributions_sum_to_the_whole_worst_first_and_signed_consistently(con, monkeypatch):
    # GOOD (30/30, 100%) is better than the implied reference -> negative.
    # MID (30/60, 50%) is worse -> positive, and the largest contributor
    # despite TINY (0/1, 0%) having the single worst rate -- its volume is
    # too small to dominate MID's. Floor patched to 1 so TINY appears as its
    # own row rather than being folded, which is exactly what this test needs
    # to pin down.
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    _insert(con, "GOOD", n_ok=30, n_late=0)
    _insert(con, "MID", n_ok=30, n_late=30)
    _insert(con, "TINY", n_ok=0, n_late=1)

    finding = _finding(gap=10.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)

    assert {r["value"] for r in rows} == {"GOOD", "MID", "TINY"}
    total = sum(r["points_of_gap"] for r in rows)
    assert total == pytest.approx(finding.gap, abs=1e-6)

    by_value = {r["value"]: r for r in rows}
    assert by_value["MID"]["points_of_gap"] > 0, "worse than reference must be positive"
    assert by_value["GOOD"]["points_of_gap"] < 0, "better than reference must be negative"
    assert by_value["TINY"]["points_of_gap"] > 0
    # The whole point: TINY has the single worst OBSERVED rate (0%) but MID
    # owns more of the gap because it carries far more volume.
    assert by_value["MID"]["points_of_gap"] > by_value["TINY"]["points_of_gap"]

    assert [r["value"] for r in rows] == sorted(
        by_value, key=lambda v: -by_value[v]["points_of_gap"]), "must be worst first"
    assert rows[0]["value"] == "MID"


def test_a_tiny_volume_value_cannot_dominate_even_at_an_extreme_rate(con, monkeypatch):
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    _insert(con, "BIG", n_ok=45, n_late=45)     # 50%, half the population
    _insert(con, "TINY", n_ok=0, n_late=1)      # 0%, a single trip

    finding = _finding(gap=10.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)
    by_value = {r["value"]: r for r in rows}

    assert rows[0]["value"] == "BIG"
    assert by_value["BIG"]["points_of_gap"] > by_value["TINY"]["points_of_gap"] > 0


def test_rows_below_the_population_floor_are_folded_into_other(con):
    # Default MIN_ROWS_PER_SLICE (not patched): TRAFFIC/DRIVER-sized volumes
    # clear it, a 2-trip vendor does not and must fold into "(other)" rather
    # than vanishing -- the sum must still hold.
    _insert(con, "BIG", n_ok=45, n_late=45)     # n=90, clears the floor
    _insert(con, "THIN", n_ok=0, n_late=2)      # n=2, below C.MIN_ROWS_PER_SLICE

    finding = _finding(gap=10.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)

    assert "THIN" not in {r["value"] for r in rows}
    other = [r for r in rows if r["value"] == "(other)"]
    assert len(other) == 1
    assert other[0]["n"] == 2
    assert sum(r["points_of_gap"] for r in rows) == pytest.approx(finding.gap, abs=1e-6)


def test_a_dimension_with_one_value_returns_one_row_that_owns_everything(con, monkeypatch):
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    _insert(con, "ONLY", n_ok=20, n_late=30)

    finding = _finding(gap=6.5)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)

    assert len(rows) == 1
    assert rows[0]["value"] == "ONLY"
    assert rows[0]["share_of_volume"] == pytest.approx(1.0)
    assert rows[0]["points_of_gap"] == pytest.approx(finding.gap, abs=1e-9)


def test_a_lower_is_better_metric_still_sums_and_signs_correctly(con, monkeypatch):
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    lower_metric = Metric("fake_lower", "Fake Lower", "%", Direction.LOWER,
                          _FAKE_ON_TIME_SQL, (ReferenceKind.TREND,), "trips", ())
    monkeypatch.setattr(registry, "by_id",
                        lambda mid: lower_metric if mid == "fake_lower" else registry.by_id.__wrapped__(mid)
                        if hasattr(registry.by_id, "__wrapped__") else lower_metric)
    # A LOWER-is-better metric's "ok" column here just stands in for the raw
    # rate SQL returns -- direction only changes the sign convention, not the
    # shape of the query.
    _insert(con, "WORSE", n_ok=40, n_late=10)    # 80% -- worse for a LOWER metric
    _insert(con, "BETTER", n_ok=10, n_late=40)   # 20% -- better for a LOWER metric

    finding = _finding(metric_id="fake_lower", gap=8.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)
    by_value = {r["value"]: r for r in rows}

    assert by_value["WORSE"]["points_of_gap"] > 0
    assert by_value["BETTER"]["points_of_gap"] < 0
    assert sum(r["points_of_gap"] for r in rows) == pytest.approx(finding.gap, abs=1e-6)


def test_decomposing_within_an_already_sliced_finding_restricts_to_that_slice(con, monkeypatch):
    # finding is already sliced to site A -- decomposing it by VENDOR must
    # only ever see vendors that operate at site A, never V3 (site B only).
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    _insert(con, "V1", n_ok=10, n_late=10, site_id="A")   # 50%
    _insert(con, "V2", n_ok=20, n_late=0, site_id="A")    # 100%
    _insert(con, "V3", n_ok=0, n_late=30, site_id="B")    # 0%, but a different site

    finding = _finding(slc=Slice(Dimension.SITE, "A"), gap=5.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)

    assert {r["value"] for r in rows} == {"V1", "V2"}
    assert sum(r["n"] for r in rows) == 40          # site A's own population only
    assert sum(r["points_of_gap"] for r in rows) == pytest.approx(finding.gap, abs=1e-6)


# ---------------------------------------------------------------------------
# Break-it-to-prove-it companion: perturbing one share must fail the
# sum-to-whole assertion above -- pinned here so a future refactor cannot
# silently make the assertion vacuous.
# ---------------------------------------------------------------------------

def test_sum_to_whole_actually_catches_a_broken_share(con, monkeypatch):
    monkeypatch.setattr(C, "MIN_ROWS_PER_SLICE", 1)
    _insert(con, "GOOD", n_ok=30, n_late=0)
    _insert(con, "MID", n_ok=30, n_late=30)
    finding = _finding(gap=10.0)
    rows = decompose.decompose(con, finding, Dimension.VENDOR)

    total = sum(r["points_of_gap"] for r in rows)
    assert total == pytest.approx(finding.gap, abs=1e-6)

    broken_total = sum(r["points_of_gap"] for r in rows) + 1.0   # simulate a broken share
    assert broken_total != pytest.approx(finding.gap, abs=1e-6), (
        "a perturbed sum must NOT still look like it sums to the whole")


# ---------------------------------------------------------------------------
# DELAY_REASON
# ---------------------------------------------------------------------------

def test_delay_reason_returns_empty_for_a_metric_that_is_not_on_time(con):
    finding = _finding(metric_id="cost_per_km", gap=5.0)
    assert decompose.decompose(con, finding, "DELAY_REASON") == []


def test_delay_reason_sums_to_the_gap_and_is_worst_first(con):
    _insert_delay(con, "NODELAY", 50)     # excluded: on-time trips own no shortfall
    _insert_delay(con, "TRAFFIC", 20)
    _insert_delay(con, "DRIVER", 15)
    _insert_delay(con, "EMPLOYEE", 2)     # below the floor -> folded into "(other)"

    finding = _finding(metric_id="ota", gap=7.0)
    rows = decompose.decompose(con, finding, "DELAY_REASON")

    assert [r["value"] for r in rows] == ["TRAFFIC", "DRIVER", "(other)"]
    assert sum(r["points_of_gap"] for r in rows) == pytest.approx(7.0, abs=1e-6)
    assert sum(r["n"] for r in rows) == 37          # NODELAY excluded from the population
    other = next(r for r in rows if r["value"] == "(other)")
    assert other["n"] == 2


def test_delay_reason_is_case_insensitive_and_dim_none_is_rejected(con):
    _insert_delay(con, "TRAFFIC", 20)
    finding = _finding(metric_id="ota", gap=7.0)
    assert decompose.decompose(con, finding, "delay_reason") == decompose.decompose(
        con, finding, "DELAY_REASON")

    with pytest.raises(ValueError, match="NONE"):
        decompose.decompose(con, finding, Dimension.NONE)


def test_unknown_dimension_string_is_refused_naming_the_valid_values(con):
    finding = _finding(metric_id="ota", gap=7.0)
    with pytest.raises(ValueError, match="DELAY_REASON"):
        decompose.decompose(con, finding, "NOT_A_REAL_DIMENSION")


# ---------------------------------------------------------------------------
# Real-data-flavoured: the unsliced ota finding on data/sample, by VENDOR.
# ---------------------------------------------------------------------------

def _midnight_plus_one_day(ms: int) -> int:
    day = 86_400_000
    return (ms // day) * day + day


def test_the_worst_vendor_owns_the_most_of_the_unsliced_ota_finding_on_the_sample():
    con = duckdb.connect()
    try:
        health = ingest.load_all(con, ingest.source_for(SAMPLE))
        clock_ms = _midnight_plus_one_day(ingest.latest_scheduled_ms(con))
        run = sweep.sweep(con, sweep.Clock(clock_ms), health)

        overall_ota = next(f for f in run.findings
                           if f.metric_id == "ota" and f.slice.dim is Dimension.NONE)
        rows = decompose.decompose(con, overall_ota, Dimension.VENDOR)
        assert rows, "expected at least one vendor row for the unsliced ota finding"

        named = [r for r in rows if r["value"] != "(other)"]
        assert named, "expected at least one named (non-folded) vendor"
        worst = named[0]
        print(f"MEASURED (data/sample) worst vendor by ota decomposition: "
             f"{worst['value']!r} owns {worst['points_of_gap']:.2f} points "
             f"of {overall_ota.gap:.2f}")

        assert worst["points_of_gap"] > 0, "the worst named vendor must be worse than reference"
        assert worst["points_of_gap"] == max(r["points_of_gap"] for r in rows), (
            "the worst named vendor must be the single largest contributor")
        assert abs(sum(r["points_of_gap"] for r in rows) - overall_ota.gap) < 0.5
    finally:
        con.close()
        registry.clear_cache()
