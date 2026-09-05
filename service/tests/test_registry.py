import pathlib

import duckdb
import pytest

from signaldesk import ingest, registry
from signaldesk.schemas import Dimension, Metric, ReferenceKind, Slice, Window

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")

# Wide enough to comfortably contain every trip in data/sample (measured
# 2026-05-01 .. 2026-07-31) without hardcoding the exact bounds.
WINDOW = Window(0, 2_000_000_000_000)

DIMENSIONS = [d for d in Dimension if d is not Dimension.NONE]


@pytest.fixture
def con():
    c = duckdb.connect()
    ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c
    c.close()
    registry.clear_cache()


# ---------------------------------------------------------------------------
# The vocabulary itself.
# ---------------------------------------------------------------------------

def test_all_five_metrics_are_defined_with_ota_first():
    assert len(registry.METRICS) == 5
    assert registry.METRICS[0].id == "ota"
    assert {m.id for m in registry.METRICS} == {
        "ota", "otd", "vendor_ota", "no_show_rate", "cost_per_km"}


def test_every_metric_declares_at_least_one_reference_point():
    # The mandatory bar is contextualisation against at least one reference
    # point. Satisfied by construction, not by a feature.
    for m in registry.METRICS:
        assert len(m.refs) >= 1


def test_no_tier_1_metric_carries_a_hard_target():
    # This task carries no TARGET at all: the real dataset's on-time rate is
    # ~59%, so a target would BREACH every slice (docs/real-dataset-mapping.md
    # §10b). A data-derived target is Task 5's job, not this one's.
    for metric_id in registry.TIER_1_METRICS:
        m = registry.by_id(metric_id)
        assert m.target is None
        assert m.hard_target is False
        assert ReferenceKind.TARGET not in m.refs


def test_an_unknown_metric_id_is_refused_with_the_valid_ids_named():
    with pytest.raises(ValueError, match="ota"):
        registry.by_id("not_a_real_metric")


def test_active_returns_exactly_the_tier_1_metrics():
    active = registry.active()
    assert {m.id for m in active} == set(registry.TIER_1_METRICS)
    assert len(active) == 4
    assert "cost_per_km" not in {m.id for m in active}


# ---------------------------------------------------------------------------
# Evaluation against the real sample data.
# ---------------------------------------------------------------------------

def test_every_metric_returns_exactly_one_number_for_the_unsliced_window(con, capsys):
    for m in registry.METRICS:
        value = registry.evaluate(con, m, Slice.all(), WINDOW)
        print(f"MEASURED {m.id} (unsliced) = {value}")
        assert isinstance(value, float)


def test_every_metric_returns_one_number_for_every_valid_slice_dimension(con):
    # DIRECTION is deliberately excluded here: ota is already LOGIN-only and
    # otd is already LOGOUT-only, so slicing ota by DIRECTION=LOGOUT (or otd by
    # LOGIN) is a structurally empty combination, not a bug -- covered
    # separately below.
    for dim in DIMENSIONS:
        if dim is Dimension.DIRECTION:
            continue
        value = registry.distinct_values(con, dim, WINDOW)[0]
        for m in registry.METRICS:
            result = registry.evaluate(con, m, Slice(dim, value), WINDOW)
            assert isinstance(result, float), (
                f"{m.id} sliced by {dim.name}={value!r} returned {result!r}")


def test_direction_slices_agree_with_each_metrics_own_direction_filter(con):
    ota, otd, vendor_ota = (registry.by_id(i) for i in ("ota", "otd", "vendor_ota"))
    assert registry.evaluate(con, ota, Slice(Dimension.DIRECTION, "LOGIN"), WINDOW) is not None
    assert registry.evaluate(con, otd, Slice(Dimension.DIRECTION, "LOGOUT"), WINDOW) is not None
    # ota is LOGIN-only, so slicing it by LOGOUT is empty by construction.
    assert registry.evaluate(con, ota, Slice(Dimension.DIRECTION, "LOGOUT"), WINDOW) is None
    assert registry.evaluate(con, otd, Slice(Dimension.DIRECTION, "LOGIN"), WINDOW) is None
    # vendor_ota carries no direction filter, so both directions return a number.
    assert registry.evaluate(con, vendor_ota, Slice(Dimension.DIRECTION, "LOGIN"), WINDOW) is not None
    assert registry.evaluate(con, vendor_ota, Slice(Dimension.DIRECTION, "LOGOUT"), WINDOW) is not None


def test_an_empty_slice_yields_none_rather_than_zero(con):
    # Not optional: this guards the worst bug in this layer. A missing slice
    # scoring 0% and breaching on a vendor that simply did not operate that
    # week is the most damaging failure mode available here.
    result = registry.evaluate(
        con, registry.by_id("ota"), Slice(Dimension.VENDOR, "NO_SUCH_VENDOR_EVER"), WINDOW)
    assert result is None


def test_coverage_ignores_a_slice_column_the_source_table_does_not_have(con):
    # BUG F3: bill has no mode/trip_direction/shift_band. cost_per_km's source
    # is "bill", so slicing coverage by MODE must measure UNSLICED coverage
    # rather than collapsing to 0.0 -- a modelling gap must not read as a wall
    # of LOW_CONFIDENCE noise.
    metric = registry.by_id("cost_per_km")
    present = {r[0] for r in con.sql("DESCRIBE bill").fetchall()}
    assert "mode" not in present and "trip_direction" not in present and "shift_band" not in present

    sliced = registry.coverage(con, metric, Slice(Dimension.MODE, "CAB"), WINDOW)
    unsliced = registry.coverage(con, metric, Slice.all(), WINDOW)
    assert sliced == unsliced

    # Absence of the metric's OWN required column is a different failure and
    # must still read as 0.0.
    fake = Metric("fake", "Fake", "%", metric.better, metric.sql, metric.refs,
                  "bill", ("column_that_does_not_exist",))
    assert registry.coverage(con, fake, Slice.all(), WINDOW) == 0.0


def test_evidence_sql_has_no_placeholders_left_and_runs_standalone(con):
    metric = registry.by_id("vendor_ota")
    slc = Slice(Dimension.VENDOR, registry.distinct_values(con, Dimension.VENDOR, WINDOW)[0])
    sql = registry.evidence_sql(metric, slc, WINDOW)

    assert "?" not in sql

    expected = registry.evaluate(con, metric, slc, WINDOW)
    (actual,) = con.sql(sql).fetchone()
    assert actual == pytest.approx(expected)


def test_the_degrading_vendor_is_visibly_worse_than_a_peer(con):
    # No planted "degrading vendor" exists in the real data -- compare the
    # worst vendor's vendor_ota against the MEDIAN vendor's, on real data.
    metric = registry.by_id("vendor_ota")
    vendors = registry.distinct_values(con, Dimension.VENDOR, WINDOW)
    scored = sorted(
        (registry.evaluate(con, metric, Slice(Dimension.VENDOR, v), WINDOW), v)
        for v in vendors
        if registry.evaluate(con, metric, Slice(Dimension.VENDOR, v), WINDOW) is not None)

    worst_value, worst_vendor = scored[0]
    median_value, median_vendor = scored[len(scored) // 2]
    print(f"MEASURED vendor_ota worst={worst_vendor!r} {worst_value:.2f} "
          f"median={median_vendor!r} {median_value:.2f}")

    assert median_value - worst_value > 10.0, "the spread must be a real margin, not noise"


# ---------------------------------------------------------------------------
# Memoisation.
# ---------------------------------------------------------------------------

def test_evaluate_is_memoised_and_clear_cache_empties_it(con):
    # duckdb's native connection object refuses attribute assignment
    # (con.execute is read-only), so the cache is verified by dict growth
    # instead of a call-counting wrapper: the cache dict must grow by exactly
    # one entry for two calls with identical arguments, proving the second
    # call was answered from the cache rather than re-running the SQL.
    registry.clear_cache()
    metric = registry.by_id("ota")
    slc = Slice.all()

    assert len(registry._CACHE) == 0
    first = registry.evaluate(con, metric, slc, WINDOW)
    assert len(registry._CACHE) == 1
    second = registry.evaluate(con, metric, slc, WINDOW)
    assert len(registry._CACHE) == 1, "a repeated call must not add a second entry"
    assert first == second

    # a different (metric, slice, window) triple is a genuine new entry
    registry.evaluate(con, registry.by_id("otd"), slc, WINDOW)
    assert len(registry._CACHE) == 2

    registry.clear_cache()
    assert len(registry._CACHE) == 0


def test_a_cached_none_is_still_returned_on_a_hit(con):
    registry.clear_cache()
    metric = registry.by_id("ota")
    slc = Slice(Dimension.VENDOR, "NO_SUCH_VENDOR_EVER")
    assert registry.evaluate(con, metric, slc, WINDOW) is None
    key = (id(con), metric.id, slc, WINDOW)
    assert key in registry._CACHE and registry._CACHE[key] is None
    # second call is a cache hit, not a fresh SQL execution that happens to
    # also return None
    assert registry.evaluate(con, metric, slc, WINDOW) is None
