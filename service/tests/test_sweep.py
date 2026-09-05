"""sweep.py: the unprompted SENSE loop and the replay clock.

Most tests run against data/sample -- the only place a real metric x slice x
window triple can be evaluated within test-suite time. One golden test (the
BREACH-count ceiling at the overall+vendor level) instead runs against
data/real and skips when that directory is absent, since a band that only
ever gets checked against the small sample is a band nobody actually
measured (see constants.py's BANDS comment and the task-5 report for the
full calibration record).
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import time
from collections import Counter

import duckdb
import pytest

from signaldesk import ingest, registry, sweep, verdict
from signaldesk.schemas import Dimension, Slice, Tier

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")
REAL_DEFAULT = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "real")


def _ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


# The clock the whole demo is built around: midnight the day after the last
# trip in data/sample (2026-07-31), matching the frozen fixture's run id
# (run-1785542400000-8) and window label (2026-07-25..2026-07-31). See
# ingest.latest_scheduled_ms and api.startup.
CLOCK_MS = _ms(2026, 8, 1)


@pytest.fixture
def con_and_health():
    c = duckdb.connect()
    health = ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c, health
    c.close()
    registry.clear_cache()


# ---------------------------------------------------------------------------
# Step 3: sweep() itself.
# ---------------------------------------------------------------------------

def test_produces_findings_without_any_prompt_or_question(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    assert len(run.findings) > 0
    assert run.window.end_ms == CLOCK_MS


def test_marshal_compliance_and_cost_per_km_both_appear_in_the_sweep(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    metric_ids = {f.metric_id for f in run.findings}
    assert "marshal_compliance" in metric_ids
    assert "cost_per_km" in metric_ids


def test_window_kind_defaults_to_week_and_a_month_window_is_28_days(con_and_health):
    con, health = con_and_health
    week = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    assert week.window_kind == "week"
    assert week.window.end_ms - week.window.start_ms == 7 * 86_400_000

    month = sweep.sweep(con, sweep.Clock(CLOCK_MS), health, window_days=28, window_kind="month")
    assert month.window_kind == "month"
    assert month.window.end_ms - month.window.start_ms == 28 * 86_400_000
    assert month.window.end_ms == week.window.end_ms == CLOCK_MS


def test_the_same_dataset_and_clock_produce_identical_findings(con_and_health):
    con, health = con_and_health
    run_a = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    run_b = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    ids_a = [f.id for f in run_a.findings]
    ids_b = [f.id for f in run_b.findings]
    assert ids_a == ids_b, "the ids must match, IN ORDER"

    observed_a = [f.observed for f in run_a.findings]
    observed_b = [f.observed for f in run_b.findings]
    assert observed_a == observed_b

    tiers_a = [f.tier for f in run_a.findings]
    tiers_b = [f.tier for f in run_b.findings]
    assert tiers_a == tiers_b


def test_findings_come_back_ranked(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    assert list(run.findings) == verdict.rank(list(run.findings)), \
        "the store must never hand back an unranked list"


def test_every_metric_slice_combination_is_visited(con_and_health, monkeypatch):
    con, health = con_and_health
    visited: set[tuple[str, Dimension, str | None]] = set()
    real = verdict.evaluate_finding

    def spy(con, metric, slc, window, feed_confidence):
        visited.add((metric.id, slc.dim, slc.value))
        return real(con, metric, slc, window, feed_confidence)

    monkeypatch.setattr(verdict, "evaluate_finding", spy)

    sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    window = sweep.Window(CLOCK_MS - 7 * 86_400_000, CLOCK_MS)
    expected: set[tuple[str, Dimension, str | None]] = set()
    for metric in registry.active(registry.TIER_1_METRICS):
        expected.add((metric.id, Dimension.NONE, None))
        # Fix-wave I3: a metric's OWN dims, not every Dimension -- ota/otd
        # exclude DIRECTION and vendor_ota is VENDOR-only.
        for dim in metric.dims:
            for value in registry.distinct_values(con, dim, window):
                expected.add((metric.id, dim, value))

    assert visited == expected


def test_ota_and_otd_never_carry_a_redundant_direction_slice(con_and_health):
    # Fix-wave I3: ota is LOGIN-only and otd is LOGOUT-only by construction
    # (their SQL hardcodes the direction filter) -- a DIRECTION slice of
    # either one used to repeat the unsliced finding's exact number under a
    # misleading label ("On-time arrival - direction LOGIN" reporting the
    # same figure as "On-time arrival - overall").
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    for f in run.findings:
        if f.metric_id in ("ota", "otd"):
            assert f.slice.dim is not Dimension.DIRECTION, (
                f"{f.metric_id} must never carry a DIRECTION slice")


def test_vendor_ota_is_sliced_only_by_vendor(con_and_health):
    # Fix-wave I3: vendor_ota answers "which vendor", never "which shift/
    # site/etc." -- 19 of 30 findings used to be non-vendor slices before
    # this fix (measured on data/sample, e.g. "Vendor on-time share - Shift:
    # Evening" ranked #3).
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    for f in run.findings:
        if f.metric_id == "vendor_ota" and f.slice.dim is not Dimension.NONE:
            assert f.slice.dim is Dimension.VENDOR


def test_owns_is_attached_for_concern_or_worse_and_empty_for_pass(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    passes = [f for f in run.findings if f.tier is Tier.PASS]
    assert passes, "fixture assumption: at least one PASS finding exists"
    for f in passes:
        assert f.owns == (), "a PASS finding must carry no owns"

    concern_or_worse = [f for f in run.findings if f.tier >= Tier.CONCERN]
    assert concern_or_worse, "fixture assumption: at least one CONCERN+ finding exists"
    with_owns = [f for f in concern_or_worse if f.owns]
    assert with_owns, "at least one CONCERN+ finding must carry owns on the sample"
    # Specifically CONCERN, not just BREACH -- pins the floor at CONCERN
    # rather than something stricter that would still pass the check above.
    assert any(f.tier is Tier.CONCERN for f in with_owns), (
        "a CONCERN (not just BREACH) finding must carry owns on the sample")
    for f in with_owns:
        assert len(f.owns) <= 2
        for value, points, n in f.owns:
            assert isinstance(value, str)
            assert points > 0, f"{f.id}'s owns must be positive (worse than reference)"
            assert n > 0


def test_the_tier_distribution_is_printed_for_calibration(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    counts = Counter(f.tier.name for f in run.findings)
    print(f"MEASURED tier distribution (data/sample, late-July week): {dict(counts)} "
          f"of {len(run.findings)} findings")
    assert sum(counts.values()) == len(run.findings)
    # Fix round 1 (Task 5 review), criterion (a): a mix across all four tiers,
    # not a wall in one of them -- MEASURED on data/sample with the
    # per-direction BANDS, after fix-wave I3 (ota/otd drop DIRECTION,
    # vendor_ota is VENDOR-only): PASS 41 / WATCH 8 / CONCERN 40 / BREACH 3
    # of 92. After Task 11 (cost_per_km + marshal_compliance activated):
    # PASS 57 / WATCH 20 / CONCERN 41 / BREACH 18 of 136 -- more findings
    # (two more active metrics) and more BREACHes (marshal_compliance's hard
    # target breaches almost every slice it produces -- see
    # test_marshal_compliance_breaches_almost_every_overall_and_vendor_slice_on_real_data).
    assert set(counts) == {"PASS", "WATCH", "CONCERN", "BREACH"}


def test_the_degrading_vendor_appears_as_a_watch_or_worse(con_and_health):
    # RE-MEASURED after the on-time redefinition (constants.py's
    # ON_TIME_GRACE_MIN comment): on-time rates jumped from ~59% to ~90%+ on
    # data/sample once on-time reads MoveInSync's own delay_minutes instead
    # of an actual_at-vs-planned_end_at comparison. The sample's worst
    # vendor_ota vendor no longer reaches CONCERN at all -- MEASURED: Arjun
    # Mikhailov Travel, 90.91% (TREND 100.0%, PEER 96.67%), WATCH via
    # TREND_REGRESSION. Reported to the controller rather than retuned: real
    # data (larger, more extreme) still produces CONCERN+ for this metric
    # (see the real-data test group below) -- the SAMPLE simply no longer
    # has an extreme-enough vendor to reach it, which is what the sample is,
    # not a bug in the bands.
    con, health = con_and_health
    window = sweep.Window(CLOCK_MS - 7 * 86_400_000, CLOCK_MS)
    metric = registry.by_id("vendor_ota")

    vendors = registry.distinct_values(con, Dimension.VENDOR, window)
    worst_vendor, worst_value = None, None
    for v in vendors:
        value = registry.evaluate(con, metric, Slice(Dimension.VENDOR, v), window)
        if value is not None and (worst_value is None or value < worst_value):
            worst_vendor, worst_value = v, value

    assert worst_vendor is not None
    finding = verdict.evaluate_finding(
        con, metric, Slice(Dimension.VENDOR, worst_vendor), window,
        feed_confidence=health[metric.source].confidence)

    assert finding is not None
    assert finding.tier >= Tier.WATCH, (
        f"worst vendor {worst_vendor} ({worst_value:.2f}%) is only {finding.tier.name}")


def test_at_least_one_vendor_ota_finding_is_watch_or_worse_on_the_sample(con_and_health):
    # Fix round 1 (Task 5 review): the golden BREACH-count assertion moved to
    # data/real below, since data/sample is too small to measure a band
    # against honestly. RE-MEASURED after the on-time redefinition: the
    # sample no longer produces a CONCERN-or-worse vendor_ota finding at all
    # (see the test above) -- this check is correspondingly WATCH-or-worse
    # now, still >=1, still what the brief's criterion (b) needs for the demo
    # to have something to show even when only the sample is available.
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    vendor_watch_or_worse = [
        f for f in run.findings
        if f.metric_id == "vendor_ota" and f.slice.dim is Dimension.VENDOR
        and f.tier >= Tier.WATCH]
    assert len(vendor_watch_or_worse) >= 1, \
        "at least one vendor_ota finding must be WATCH-or-worse on the sample"


# Fix round 1 (Task 5 review): this is now the ONLY BREACH-count assertion,
# and it runs against data/real, not data/sample -- a range reverse-engineered
# from what the small sample happened to produce is not a measurement.
# MEASURED on data/real (615k trips), late-July week 2026-07-25..2026-07-31,
# with the calibrated per-direction BANDS: 7 BREACH findings at the
# overall+vendor level (2 HIGHER -- ota and vendor_ota, both `vendor Pooja
# Sokolov Travel` -- plus 5 LOWER -- no_show_rate, across sites and vendors).
# See constants.py's BANDS comment for the full per-direction distributions.
#
# Task 11: this ceiling is scoped to the BANDS-governed (soft-tiered) metrics
# ONLY -- excludes any metric with hard_target=True. marshal_compliance
# (activated by Task 11) is a hard target: it breaches on ANY shortfall by
# construction (deviation 2), so "almost every slice breaches" is the
# EXPECTED shape for it, not the wall-of-BREACH regression this ceiling
# exists to catch for a soft-banded metric. Re-measured after activating
# cost_per_km and marshal_compliance: still exactly 7 -- unchanged, since
# cost_per_km contributes 0 overall+vendor BREACHes this window (its
# outliers this week are SITE-level, e.g. Boulder Campus, not overall/vendor).
REAL_DATA = os.environ.get("SIGNALDESK_REAL_DATA", REAL_DEFAULT)
BREACH_COUNT_AT_OVERALL_AND_VENDOR_LEVEL_ON_REAL = 7


def test_breach_count_at_overall_and_vendor_level_stays_within_the_measured_ceiling_on_real_data():
    if not pathlib.Path(REAL_DATA).is_dir():
        pytest.skip(f"no dataset at {REAL_DATA} (set SIGNALDESK_REAL_DATA to point at data/real)")

    con = duckdb.connect()
    try:
        health = ingest.load_all(con, ingest.source_for(REAL_DATA))
        clock_ms = _midnight_plus_one_day(ingest.latest_scheduled_ms(con))
        run = sweep.sweep(con, sweep.Clock(clock_ms), health)
    finally:
        con.close()
        registry.clear_cache()

    overall_vendor_breaches = [
        f for f in run.findings
        if f.tier is Tier.BREACH and f.slice.dim in (Dimension.NONE, Dimension.VENDOR)
        and not registry.by_id(f.metric_id).hard_target]

    assert 1 <= len(overall_vendor_breaches) <= BREACH_COUNT_AT_OVERALL_AND_VENDOR_LEVEL_ON_REAL, (
        f"got {len(overall_vendor_breaches)} overall+vendor BREACH findings (soft-banded metrics "
        f"only) on {REAL_DATA}; expected 1..{BREACH_COUNT_AT_OVERALL_AND_VENDOR_LEVEL_ON_REAL} "
        f"(the ceiling measured against data/real -- see constants.py's BANDS comment)")


def test_real_data_still_produces_concern_or_worse_on_time_findings_after_the_redefinition():
    # On-time redefinition sanity check: data/sample's worst vendor_ota
    # vendor no longer reaches CONCERN at all (see the two WATCH-or-worse
    # tests above) -- confirm the real dataset still does, so "HIGHER bands
    # produce zero BREACH on real data" (the condition that would need a
    # controller recalibration ruling) is NOT what happened. RE-MEASURED:
    # Pooja Sokolov Travel is BREACH on BOTH ota (20.65%, gap 71.78) and
    # vendor_ota (20.65%, gap 75.30) -- the same vendor, the same tier, as
    # before the redefinition -- a genuinely, persistently bad vendor
    # regardless of which on-time definition is used.
    if not pathlib.Path(REAL_DATA).is_dir():
        pytest.skip(f"no dataset at {REAL_DATA} (set SIGNALDESK_REAL_DATA to point at data/real)")

    con = duckdb.connect()
    try:
        health = ingest.load_all(con, ingest.source_for(REAL_DATA))
        clock_ms = _midnight_plus_one_day(ingest.latest_scheduled_ms(con))
        run = sweep.sweep(con, sweep.Clock(clock_ms), health)
    finally:
        con.close()
        registry.clear_cache()

    for mid in ("ota", "vendor_ota"):
        concern_or_worse = [
            f for f in run.findings
            if f.metric_id == mid and f.slice.dim in (Dimension.NONE, Dimension.VENDOR)
            and f.tier >= Tier.CONCERN]
        assert concern_or_worse, f"{mid} must still produce a CONCERN+ overall/vendor finding on real data"


# Task 11: marshal_compliance's OWN overall+vendor BREACH count, measured and
# reported separately from the soft-banded ceiling above -- a hard target
# metric breaching almost everywhere is the honest shape of the data (real
# escort compliance is far from 100% nearly everywhere), not a regression.
# MEASURED on data/real: overall compliance 32.6% (n=16,502, the swept week);
# 23 of 24 possible overall+vendor slices (23 vendors + overall) BREACH; the
# one vendor that does not is still only 61.2% compliant -- every single
# overall+vendor slice this metric can produce is at or below CONCERN.
def test_marshal_compliance_breaches_almost_every_overall_and_vendor_slice_on_real_data():
    if not pathlib.Path(REAL_DATA).is_dir():
        pytest.skip(f"no dataset at {REAL_DATA} (set SIGNALDESK_REAL_DATA to point at data/real)")

    con = duckdb.connect()
    try:
        health = ingest.load_all(con, ingest.source_for(REAL_DATA))
        clock_ms = _midnight_plus_one_day(ingest.latest_scheduled_ms(con))
        run = sweep.sweep(con, sweep.Clock(clock_ms), health)
    finally:
        con.close()
        registry.clear_cache()

    marshal_overall_vendor = [
        f for f in run.findings
        if f.metric_id == "marshal_compliance" and f.slice.dim in (Dimension.NONE, Dimension.VENDOR)]
    assert marshal_overall_vendor, "fixture assumption: marshal_compliance produced overall/vendor findings"

    breaches = [f for f in marshal_overall_vendor if f.tier is Tier.BREACH]
    print(f"MEASURED (data/real) marshal_compliance: {len(breaches)}/{len(marshal_overall_vendor)} "
          f"overall+vendor slices BREACH (a hard target -- any shortfall breaches)")
    assert len(breaches) >= len(marshal_overall_vendor) - 1, (
        "a hard target with real-world compliance well under 100% should breach "
        "at nearly every slice -- a sudden mostly-PASS result would itself be suspicious")


def _midnight_plus_one_day(ms: int) -> int:
    day = 86_400_000
    return (ms // day) * day + day


# ---------------------------------------------------------------------------
# The replay clock -- pure, no DuckDB, no real sleeping.
# ---------------------------------------------------------------------------

def test_the_replay_clock_advances_the_simulated_date_while_running():
    clock = sweep.ReplayClock(now_ms=1_000_000, speed=1_000_000.0)
    before = clock.millis()
    clock.start()
    time.sleep(0.01)
    after = clock.millis()
    assert after > before


def test_the_replay_clock_is_frozen_when_stopped():
    clock = sweep.ReplayClock(now_ms=1_000_000, speed=1_000_000.0)
    clock.start()
    time.sleep(0.01)
    clock.stop()
    frozen = clock.millis()
    time.sleep(0.01)
    assert clock.millis() == frozen


def test_a_stopped_replay_clock_keeps_the_time_it_reached():
    clock = sweep.ReplayClock(now_ms=1_000_000, speed=1_000_000.0)
    clock.start()
    time.sleep(0.01)
    clock.stop()
    assert clock.now_ms > 1_000_000
    assert clock.millis() == clock.now_ms
