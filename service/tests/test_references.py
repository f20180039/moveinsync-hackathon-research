"""references.resolve() against the real sample data.

Every number asserted here was measured directly against data/sample before
being written down (see the exploration in the task-4 report), never derived
by re-running the implementation under test on itself.
"""
import datetime as dt
import pathlib

import duckdb
import pytest

from signaldesk import ingest, references, registry
from signaldesk.schemas import Dimension, Direction, Metric, Reference, ReferenceKind, Slice, Window

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")

# Wide enough to comfortably contain every trip in data/sample (measured
# 2026-05-01 .. 2026-07-31) without hardcoding the exact bounds.
FULL = Window(0, 2_000_000_000_000)


def _ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


# A one-week window ending late July: four full preceding weeks, all inside
# the sample's data range, so both TREND and a >=4-value PEER dimension
# resolve for the same slice.
LATE_JULY = Window.week_ending(_ms(2026, 7, 31))

# A window early enough that some (but not all) of its four preceding weeks
# fall before the sample's 2026-05-01 start.
NEAR_START = Window.week_ending(_ms(2026, 5, 22))

# A window so early that ALL four preceding weeks fall before the data starts.
BEFORE_DATA = Window.week_ending(_ms(2026, 5, 1))


@pytest.fixture
def con():
    c = duckdb.connect()
    ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c
    c.close()
    registry.clear_cache()


def _refs_by_kind(refs):
    return {r.kind: r for r in refs}


# ---------------------------------------------------------------------------
# _trend, via resolve()
# ---------------------------------------------------------------------------

def test_trend_is_the_mean_of_the_four_preceding_windows_and_excludes_the_evaluated_one(con):
    metric = registry.by_id("vendor_ota")
    slc = Slice(Dimension.SHIFT, "DAY")

    # Independently computed expectation: the mean of the four windows
    # strictly BEFORE the one under evaluation.
    preceding = [registry.evaluate(con, metric, slc, LATE_JULY.shifted_back(b))
                 for b in range(1, 5)]
    assert all(v is not None for v in preceding), "fixture assumption: all four preceding weeks have data"
    expected = sum(preceding) / len(preceding)

    trend = _refs_by_kind(references.resolve(con, metric, slc, LATE_JULY))[ReferenceKind.TREND]
    assert trend.value == pytest.approx(expected)

    # The evaluated window's own value differs materially from the trend of
    # the four PRECEDING weeks -- an off-by-one that folded it in (range(0, ...)
    # instead of range(1, ...)) would shift the mean measurably.
    observed = registry.evaluate(con, metric, slc, LATE_JULY)
    assert observed != pytest.approx(trend.value, rel=1e-3)


def test_trend_averages_only_the_windows_that_returned_a_value(con):
    metric = registry.by_id("ota")
    slc = Slice.all()

    preceding = [registry.evaluate(con, metric, slc, NEAR_START.shifted_back(b))
                 for b in range(1, 5)]
    present = [v for v in preceding if v is not None]
    assert 0 < len(present) < 4, "fixture assumption: some but not all preceding weeks have data"
    expected = sum(present) / len(present)

    trend = _refs_by_kind(references.resolve(con, metric, slc, NEAR_START))[ReferenceKind.TREND]
    assert trend.value == pytest.approx(expected)


def test_trend_is_omitted_when_no_preceding_window_has_data(con):
    metric = registry.by_id("ota")
    slc = Slice.all()

    preceding = [registry.evaluate(con, metric, slc, BEFORE_DATA.shifted_back(b))
                 for b in range(1, 5)]
    assert all(v is None for v in preceding), "fixture assumption: no preceding week has data"

    refs = references.resolve(con, metric, slc, BEFORE_DATA)
    assert ReferenceKind.TREND not in {r.kind for r in refs}


# ---------------------------------------------------------------------------
# _peer, via resolve()
# ---------------------------------------------------------------------------

def test_peer_is_the_median_across_the_other_values_of_the_same_dimension(con):
    metric = registry.by_id("vendor_ota")
    subject = Slice(Dimension.SHIFT, "DAY")

    peer_values = sorted(
        registry.evaluate(con, metric, Slice(Dimension.SHIFT, v), LATE_JULY)
        for v in registry.distinct_values(con, Dimension.SHIFT, LATE_JULY)
        if v != "DAY")
    assert len(peer_values) == 3, "fixture assumption: three peer shifts, all computable"
    expected_median = peer_values[1]

    peer = _refs_by_kind(references.resolve(con, metric, subject, LATE_JULY))[ReferenceKind.PEER]
    assert peer.value == pytest.approx(expected_median)


def test_peer_is_omitted_rather_than_computed_on_two_peers(con):
    # MODE has exactly three distinct values (BUS, CAB, SPOT_2.0), all
    # computable for "ota" over the full sample -- so excluding the subject
    # leaves exactly two peers, one short of MIN_PEERS.
    metric = registry.by_id("ota")
    modes = registry.distinct_values(con, Dimension.MODE, FULL)
    assert modes == ["BUS", "CAB", "SPOT_2.0"]
    for m in modes:
        assert registry.evaluate(con, metric, Slice(Dimension.MODE, m), FULL) is not None

    refs = references.resolve(con, metric, Slice(Dimension.MODE, "BUS"), FULL)
    assert ReferenceKind.PEER not in {r.kind for r in refs}


def test_peer_is_omitted_for_an_unsliced_finding(con):
    metric = registry.by_id("vendor_ota")
    refs = references.resolve(con, metric, Slice.all(), LATE_JULY)
    assert ReferenceKind.PEER not in {r.kind for r in refs}


# ---------------------------------------------------------------------------
# Declaration order and TARGET (Controller ruling 1).
# ---------------------------------------------------------------------------

def test_references_come_back_in_declaration_order_so_tie_breaking_is_stable(con):
    metric = registry.by_id("vendor_ota")
    assert metric.refs == (ReferenceKind.TREND, ReferenceKind.PEER)

    refs = references.resolve(con, metric, Slice(Dimension.SHIFT, "DAY"), LATE_JULY)
    assert [r.kind for r in refs] == [ReferenceKind.TREND, ReferenceKind.PEER]


def test_target_reference_is_the_declared_target_value_and_needs_no_computation():
    # Controller ruling 1: no metric in the current registry declares TARGET
    # (Task 11 adds one), so the TARGET branch of resolve() is exercised here
    # with a Metric built inline. It never touches con or runs metric.sql --
    # con=None proves it.
    metric = Metric("fake_target", "Fake", "%", Direction.HIGHER,
                     "-- never executed {{SLICE}}", (ReferenceKind.TARGET,),
                     "trips", (), target=95.0, hard_target=True)

    refs = references.resolve(None, metric, Slice.all(), LATE_JULY)
    assert refs == (Reference(ReferenceKind.TARGET, 95.0, "SLA target"),)
