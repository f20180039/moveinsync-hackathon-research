import pytest

from signaldesk.schemas import (Audience, Cause, Dimension, Direction, Finding,
                                Metric, Reference, ReferenceKind, Slice, Tier,
                                Window, finding_id)


def test_tiers_compare_ordinally_and_a_breach_beats_any_watch():
    assert Tier.BREACH > Tier.CONCERN > Tier.WATCH > Tier.PASS
    assert max([Tier.WATCH, Tier.WATCH, Tier.WATCH, Tier.BREACH]) is Tier.BREACH


def test_an_unknown_dimension_is_refused_with_the_valid_values_named():
    with pytest.raises(ValueError, match="route"):
        Dimension.parse("route")
    with pytest.raises(ValueError, match="VENDOR"):
        Dimension.parse("route")


def test_a_slice_must_agree_with_its_dimension():
    assert Slice.all().label == "overall"
    assert Slice(Dimension.VENDOR, "V07").label == "vendor V07"
    with pytest.raises(ValueError):
        Slice(Dimension.VENDOR, None)
    with pytest.raises(ValueError):
        Slice(Dimension.NONE, "V07")


def test_trend_windows_are_the_four_preceding_ones_and_exclude_the_evaluated_window():
    w = Window.week_ending(10 * 7 * 86_400_000)
    assert w.shifted_back(1).end_ms == w.start_ms
    assert w.shifted_back(4).start_ms == w.start_ms - 4 * (w.end_ms - w.start_ms)


def test_a_metric_declaring_a_target_must_have_one_and_vice_versa():
    with pytest.raises(ValueError, match="TARGET"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1 {{SLICE}}",
               (ReferenceKind.TREND,), "trips", (), target=90.0)
    with pytest.raises(ValueError, match="TARGET"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1 {{SLICE}}",
               (ReferenceKind.TARGET,), "trips", ())


def test_a_metric_without_a_slice_token_is_refused():
    with pytest.raises(ValueError, match="SLICE"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1",
               (ReferenceKind.TREND,), "trips", ())


def _finding(tier, gap):
    w = Window.week_ending(10 * 7 * 86_400_000)
    return Finding("f1", "ota", Slice.all(), w, 78.0,
                   (Reference(ReferenceKind.TARGET, 90.0, "SLA target"),),
                   tier, Cause.BELOW_TARGET, gap, 0.97,
                   frozenset({Audience.TRANSPORT_MANAGER}), "SELECT 1")


def test_a_pass_cannot_be_constructed_with_a_worse_than_reference_gap():
    # A sign-flipped gap produces a confidently wrong sentence, so it is made
    # impossible to construct rather than merely unlikely.
    _finding(Tier.PASS, -1.0)
    _finding(Tier.BREACH, 12.0)
    with pytest.raises(ValueError, match="PASS"):
        _finding(Tier.PASS, 12.0)


def test_finding_ids_are_stable_across_calls_and_distinct_across_slices():
    w = Window.week_ending(10 * 7 * 86_400_000)
    assert finding_id("ota", Slice.all(), w) == finding_id("ota", Slice.all(), w)
    assert finding_id("ota", Slice.all(), w) != finding_id(
        "ota", Slice(Dimension.VENDOR, "V07"), w)
    assert finding_id("ota", Slice.all(), w) != finding_id("sla_breach", Slice.all(), w)


def test_confidence_disclosure_threshold_is_nine_tenths():
    assert _finding(Tier.BREACH, 12.0).must_disclose_confidence is False
    w = Window.week_ending(10 * 7 * 86_400_000)
    low = Finding("f2", "ota", Slice.all(), w, 78.0, (), Tier.WATCH,
                  Cause.LOW_CONFIDENCE, 12.0, 0.62,
                  frozenset({Audience.TRANSPORT_MANAGER}), "SELECT 1")
    assert low.must_disclose_confidence is True
