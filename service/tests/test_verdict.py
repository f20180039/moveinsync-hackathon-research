"""verdict.py: pure-function tests build Finding/Reference objects directly
(no DuckDB); evaluate_finding tests run against data/sample, since that is
the only place a real Metric x Slice x Window triple can be evaluated.
"""
import datetime as dt
import pathlib

import duckdb
import pytest

from signaldesk import constants as C, ingest, registry, verdict
from signaldesk.schemas import (Audience, Cause, Dimension, Direction, Finding,
                                Metric, Reference, ReferenceKind, Slice, Tier, Window)

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")


def _ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


LATE_JULY = Window.week_ending(_ms(2026, 7, 31))
BEFORE_DATA = Window.week_ending(_ms(2026, 1, 1))


@pytest.fixture
def con():
    c = duckdb.connect()
    ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c
    c.close()
    registry.clear_cache()


def _finding(tier, gap, confidence=1.0, suffix="x", cause=None):
    """A minimal, otherwise-valid Finding for the pure rank()/audiences_for
    tests. Never touches DuckDB."""
    if cause is None:
        cause = Cause.ON_REFERENCE if tier is Tier.PASS else Cause.PEER_LAGGARD
    return Finding(f"id-{suffix}", "ota", Slice.all(), Window(0, 1), 50.0, (),
                   tier, cause, gap, confidence, frozenset(), "")


# ---------------------------------------------------------------------------
# delta()
# ---------------------------------------------------------------------------

def test_one_formula_covers_both_directions():
    reference = 100.0
    # HIGHER-worse: falling short of a reference you want to exceed is worse.
    assert verdict.delta(90.0, reference, Direction.HIGHER) == pytest.approx(0.10)
    # HIGHER-better: exceeding it is better (negative).
    assert verdict.delta(110.0, reference, Direction.HIGHER) == pytest.approx(-0.10)
    # LOWER-worse: exceeding a reference you want to stay under is worse.
    assert verdict.delta(110.0, reference, Direction.LOWER) == pytest.approx(0.10)
    # LOWER-better: staying under it is better (negative).
    assert verdict.delta(90.0, reference, Direction.LOWER) == pytest.approx(-0.10)


def test_a_zero_reference_saturates_rather_than_dividing_by_zero():
    # observed also zero: no shortfall at all, whichever direction.
    assert verdict.delta(0.0, 0.0, Direction.HIGHER) == 0.0
    assert verdict.delta(0.0, 0.0, Direction.LOWER) == 0.0
    # LOWER-is-better metric, reference of 0, any positive observed is a
    # shortfall that cannot be expressed as a fraction of zero -- saturate worst.
    assert verdict.delta(5.0, 0.0, Direction.LOWER) == 1.0
    # HIGHER-is-better metric, reference of 0, any positive observed already
    # beats the reference -- saturate best.
    assert verdict.delta(5.0, 0.0, Direction.HIGHER) == -1.0


def test_gap_sign_agrees_with_tier_for_both_directions():
    reference = 100.0
    cases = [
        # (better, observed, expect_worse)
        (Direction.HIGHER, 80.0, True),    # HIGHER-worse
        (Direction.LOWER, 120.0, True),    # LOWER-worse
        (Direction.HIGHER, 120.0, False),  # HIGHER-better
        (Direction.LOWER, 80.0, False),    # LOWER-better
    ]
    for better, observed, expect_worse in cases:
        d = verdict.delta(observed, reference, better)
        gap = d * reference
        tier = verdict.tier_for(d, hard_target=False)
        if expect_worse:
            assert gap > 0
            assert tier is not Tier.PASS
        else:
            assert gap < 0
            assert tier is Tier.PASS


# ---------------------------------------------------------------------------
# tier_for()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("d, expected", [
    (C.PASS_MAX, Tier.PASS),                    # inclusive upward boundary
    (C.PASS_MAX + 1e-9, Tier.WATCH),
    (C.WATCH_MAX, Tier.WATCH),                  # inclusive upward boundary
    (C.WATCH_MAX + 1e-9, Tier.CONCERN),
    (C.CONCERN_MAX, Tier.CONCERN),               # inclusive upward boundary
    (C.CONCERN_MAX + 1e-9, Tier.BREACH),
    (-1.0, Tier.PASS),                          # far better than reference
])
def test_all_four_tiers_are_reachable_and_boundaries_are_inclusive_upward(d, expected):
    assert verdict.tier_for(d, hard_target=False) is expected


def test_a_hard_target_breaches_on_any_shortfall_at_all():
    # Controller ruling 1: no registry metric declares a hard target yet
    # (Task 11 adds one) -- tier_for's hard_target branch is pure and needs no
    # Metric at all, so it is exercised directly.
    assert verdict.tier_for(0.0001, hard_target=True) is Tier.BREACH
    assert verdict.tier_for(0.0, hard_target=True) is Tier.PASS
    assert verdict.tier_for(-0.3, hard_target=True) is Tier.PASS


# ---------------------------------------------------------------------------
# rank()
# ---------------------------------------------------------------------------

def test_one_breach_outranks_twenty_watches():
    # The property a weighted score would violate: no number of WATCHes,
    # however large their gaps, may outrank a single BREACH with a tiny one.
    watches = [_finding(Tier.WATCH, gap=100.0 + i, suffix=f"w{i}") for i in range(20)]
    breach = _finding(Tier.BREACH, gap=0.01, suffix="breach")

    ranked = verdict.rank(watches + [breach])
    assert ranked[0] is breach


# ---------------------------------------------------------------------------
# audiences_for()
# ---------------------------------------------------------------------------

def test_a_breach_sliced_by_shift_reaches_all_three_audiences():
    audiences = verdict.audiences_for("ota", Slice(Dimension.SHIFT, "NIGHT"), Tier.BREACH)
    assert audiences == frozenset(Audience)


# ---------------------------------------------------------------------------
# evaluate_finding() -- against data/sample.
# ---------------------------------------------------------------------------

def test_takes_the_worst_tier_across_every_reference_and_keeps_them_all(con):
    # MEASURED on data/sample, vendor_ota sliced by SHIFT=EVENING, LATE_JULY:
    # observed 36.07, TREND 29.18 (PASS), PEER 57.58. Tier CONCERN, not BREACH,
    # since Task 5's calibration against data/real widened CONCERN_MAX from
    # 0.15 to 1.90 (see constants.py's before/after record) -- this case's
    # delta (~0.374) sits inside the wider band now. The worst tier (via the
    # peer reference) still wins over TREND's PASS, and both references still
    # survive on the finding -- neither is discarded once the worst is chosen,
    # which is what this test is actually pinning down.
    metric = registry.by_id("vendor_ota")
    slc = Slice(Dimension.SHIFT, "EVENING")

    finding = verdict.evaluate_finding(con, metric, slc, LATE_JULY, feed_confidence=1.0)

    assert finding is not None
    assert finding.tier is Tier.CONCERN
    assert {r.kind for r in finding.refs} == {ReferenceKind.TREND, ReferenceKind.PEER}
    assert finding.cause is Cause.PEER_LAGGARD
    assert finding.gap > 0


def test_a_passing_metric_carries_no_accusatory_cause(con):
    # MEASURED on data/sample, ota sliced by SHIFT=EVENING, LATE_JULY:
    # observed 81.82, TREND 77.08 and PEER 80.0 both PASS.
    metric = registry.by_id("ota")
    slc = Slice(Dimension.SHIFT, "EVENING")

    finding = verdict.evaluate_finding(con, metric, slc, LATE_JULY, feed_confidence=1.0)

    assert finding is not None
    assert finding.tier is Tier.PASS
    assert finding.cause is Cause.ON_REFERENCE
    assert finding.gap <= 0


def test_a_within_tolerance_pass_never_carries_a_positive_gap(con):
    # Bug found running the full Tier-1 metric x slice sweep (see task-4
    # report): C.PASS_MAX is a TOLERANCE, so tier_for(d) can still say PASS
    # for a small POSITIVE d (marginally worse than the reference but inside
    # tolerance). Two data points, per ruling 5, both landing in the
    # (0, PASS_MAX] band by a different route.

    # 1) MEASURED on data/sample, otd unsliced, LATE_JULY: observed 34.375
    # vs TREND 35.02, d=0.0184 <= PASS_MAX=0.02 -> PASS, yet the raw gap
    # (d x reference) is +0.65 -- which Finding.__post_init__ correctly
    # refuses on a PASS. This is the case that used to raise ValueError.
    metric = registry.by_id("otd")
    finding = verdict.evaluate_finding(con, metric, Slice.all(), LATE_JULY, feed_confidence=1.0)
    assert finding is not None
    assert finding.tier is Tier.PASS
    assert finding.gap <= 0

    # 2) Synthetic: a metric whose value is a deterministic linear function of
    # the window's start_ms (never touches trips/bill -- the two "?" just
    # bind window.start_ms/end_ms as registry.evaluate always requires). Its
    # four-week TREND lands a hair above its observed value: d ~= 0.00025,
    # comfortably inside (0, PASS_MAX] -- a different metric, a different
    # reference kind (TREND vs the real case's TREND-that-happened-to-fire),
    # and a hand-verified exact value rather than a real-data coincidence.
    fake = Metric("fake_linear_trend", "Fake", "%", Direction.HIGHER,
                  "SELECT 100.0 - 0.00000001 * CAST(? AS DOUBLE) "
                  "WHERE ? IS NOT NULL {{SLICE}}",
                  (ReferenceKind.TREND,), "trips", ())
    tiny_window = Window(1_000_000, 2_000_000)

    synthetic = verdict.evaluate_finding(con, fake, Slice.all(), tiny_window, feed_confidence=1.0)
    assert synthetic is not None
    assert synthetic.tier is Tier.PASS
    assert synthetic.gap == 0.0


def test_low_confidence_caps_at_watch_and_says_why(con):
    # Same BREACH-by-peer case as above, but a near-zero feed confidence must
    # cap the tier at WATCH and relabel the cause, never improve it.
    metric = registry.by_id("vendor_ota")
    slc = Slice(Dimension.SHIFT, "EVENING")

    finding = verdict.evaluate_finding(con, metric, slc, LATE_JULY, feed_confidence=0.1)

    assert finding is not None
    assert finding.confidence < C.MIN_TRUSTED_CONFIDENCE
    assert finding.tier is Tier.WATCH
    assert finding.cause is Cause.LOW_CONFIDENCE


def test_low_confidence_does_not_promote_a_pass_to_a_watch(con):
    # Same PASS case as above: low confidence must not turn a clean PASS into
    # a WATCH -- the cap only ever lowers severity, never adds it.
    metric = registry.by_id("ota")
    slc = Slice(Dimension.SHIFT, "EVENING")

    finding = verdict.evaluate_finding(con, metric, slc, LATE_JULY, feed_confidence=0.1)

    assert finding is not None
    assert finding.confidence < C.MIN_TRUSTED_CONFIDENCE
    assert finding.tier is Tier.PASS
    assert finding.cause is Cause.ON_REFERENCE


def test_an_unmeasurable_overall_metric_is_a_finding_not_silence(con):
    metric = registry.by_id("ota")
    assert registry.evaluate(con, metric, Slice.all(), BEFORE_DATA) is None

    finding = verdict.evaluate_finding(con, metric, Slice.all(), BEFORE_DATA, feed_confidence=1.0)

    assert finding is not None
    assert finding.tier is Tier.WATCH
    assert finding.cause is Cause.DATA_GAP
    assert finding.refs == ()


def test_an_empty_slice_is_skipped_rather_than_reported_as_a_gap(con):
    metric = registry.by_id("ota")
    slc = Slice(Dimension.VENDOR, "NO_SUCH_VENDOR_EVER")
    assert registry.evaluate(con, metric, slc, LATE_JULY) is None

    finding = verdict.evaluate_finding(con, metric, slc, LATE_JULY, feed_confidence=1.0)
    assert finding is None


def test_a_metric_with_no_computable_reference_emits_nothing(con):
    # Controller ruling 3: an unsliced slice on a synthetic metric whose SQL
    # returns a number but whose only declared reference is PEER -- peer is
    # always omitted for an unsliced finding, so no reference resolves and the
    # metric is silently uncontextualisable.
    fake = Metric("fake_peer_only", "Fake", "%", Direction.HIGHER,
                  "SELECT 42.0 WHERE ? IS NOT NULL AND ? IS NOT NULL {{SLICE}}",
                  (ReferenceKind.PEER,), "trips", ())

    assert registry.evaluate(con, fake, Slice.all(), LATE_JULY) == 42.0
    finding = verdict.evaluate_finding(con, fake, Slice.all(), LATE_JULY, feed_confidence=1.0)
    assert finding is None
