"""sweep.py: the unprompted SENSE loop and the replay clock.

Tests run against data/sample -- the only place a real metric x slice x
window triple can be evaluated within test-suite time. See the task-5 report
for the calibration run against data/real that pinned constants.py.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import time
from collections import Counter

import duckdb
import pytest

from signaldesk import constants as C, ingest, registry, sweep, verdict
from signaldesk.schemas import Dimension, Slice, Tier

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")


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
        for dim in Dimension:
            if dim is Dimension.NONE:
                continue
            for value in registry.distinct_values(con, dim, window):
                expected.add((metric.id, dim, value))

    assert visited == expected


def test_the_tier_distribution_is_printed_for_calibration(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    counts = Counter(f.tier.name for f in run.findings)
    print(f"MEASURED tier distribution (data/sample, late-July week): {dict(counts)} "
          f"of {len(run.findings)} findings")
    assert sum(counts.values()) == len(run.findings)


def test_the_degrading_vendor_appears_as_a_concern_or_worse(con_and_health):
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
    assert finding.tier >= Tier.CONCERN, (
        f"worst vendor {worst_vendor} ({worst_value:.2f}%) is only {finding.tier.name}")


# Controller ruling 6: pinned at ~80% of what was MEASURED on data/sample
# after calibration -- PASS 97 / WATCH 37 / CONCERN 63 / BREACH 1 of 197 (see
# the task-5 report for the before/after numbers on data/real). Re-measure
# with test_the_tier_distribution_is_printed_for_calibration's printed line
# if constants.py moves again.
SAMPLE_BREACH_COUNT_AFTER_CALIBRATION = 1


def test_breach_count_stays_within_the_calibrated_golden_range(con_and_health):
    con, health = con_and_health
    run = sweep.sweep(con, sweep.Clock(CLOCK_MS), health)

    breaches = [f for f in run.findings if f.tier is Tier.BREACH]
    upper = max(1, round(0.8 * SAMPLE_BREACH_COUNT_AFTER_CALIBRATION))
    assert 1 <= len(breaches) <= upper, (
        f"got {len(breaches)} BREACH findings; expected 1..{upper} "
        f"(80% of the {SAMPLE_BREACH_COUNT_AFTER_CALIBRATION} measured after calibration)")

    vendor_breach_or_worse = [
        f for f in run.findings
        if f.metric_id == "vendor_ota" and f.slice.dim is Dimension.VENDOR
        and f.tier >= Tier.CONCERN]
    assert len(vendor_breach_or_worse) >= 1, \
        "at least one vendor_ota finding must be CONCERN-or-worse"


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
