"""actions.py: the deterministic (metric_id, cause) -> imperative lookup.

Built against real Finding dataclasses, same pattern as test_compose.py.
"""
from __future__ import annotations

import pytest

from signaldesk.actions import _ACTIONS, _BY_CAUSE, action_for
from signaldesk.compose import _SYSTEM_PROMPT, _action_sentence, _findings_as_text, template_brief
from signaldesk.schemas import (Audience, Cause, Dimension, FeedHealth, Finding,
                                Reference, ReferenceKind, Slice, Tier, Window,
                                finding_id)
from signaldesk.sweep import SweepRun
from signaldesk import registry

WINDOW = Window(1_000_000_000_000, 1_000_604_800_000)


def _finding(metric_id="vendor_ota", slc=None, observed=61.4, refs=None,
            tier=Tier.BREACH, cause=Cause.PEER_LAGGARD, gap=25.0, confidence=0.95,
            audiences=frozenset({Audience.TRANSPORT_MANAGER, Audience.FACILITIES_HEAD})):
    slc = slc if slc is not None else Slice(Dimension.VENDOR, "Aarav Petrov Travel")
    refs = refs if refs is not None else (
        Reference(ReferenceKind.TREND, 55.0, "4-week average"),
        Reference(ReferenceKind.PEER, 60.0, "peer median"))
    return Finding(finding_id(metric_id, slc, WINDOW), metric_id, slc, WINDOW, observed,
                  refs, tier, cause, gap, confidence, audiences,
                  f"SELECT observed FROM trips WHERE trip_id = 'evidence-only-{metric_id}'")


def _run(findings, feed_health=None):
    feed_health = feed_health if feed_health is not None else {
        "trips": FeedHealth("trips", 10_000, 100, 10, 5, 0.98),
    }
    return SweepRun("run-test", WINDOW, tuple(findings), feed_health, WINDOW.end_ms)


# ---------------------------------------------------------------------------
# action_for
# ---------------------------------------------------------------------------

def test_every_registry_metric_and_cause_in_play_has_an_action_or_an_explicit_blank():
    causes_in_play = (Cause.TREND_REGRESSION, Cause.PEER_LAGGARD, Cause.LOW_CONFIDENCE,
                      Cause.DATA_GAP, Cause.BELOW_TARGET)
    for metric in registry.METRICS:
        for cause in causes_in_play:
            f = _finding(metric_id=metric.id, cause=cause, tier=Tier.CONCERN)
            action = action_for(f)
            # Either a real sentence, or the deliberate '' -- never missing entirely.
            assert isinstance(action, str)


def test_a_pass_returns_an_empty_string_not_a_filler_sentence():
    f = _finding(tier=Tier.PASS, cause=Cause.ON_REFERENCE, gap=0.0)
    assert action_for(f) == ""


def test_an_unmapped_metric_falls_back_to_the_cause_level_line():
    f = _finding(metric_id="no_show_rate", cause=Cause.TREND_REGRESSION, tier=Tier.CONCERN)
    assert ("no_show_rate", Cause.TREND_REGRESSION) not in _ACTIONS
    action = action_for(f)
    assert action != ""
    assert action == _BY_CAUSE[Cause.TREND_REGRESSION].format(
        slice_value=f.slice.value)


def test_the_slice_value_is_interpolated_and_an_unsliced_finding_reads_sensibly():
    sliced = _finding(metric_id="vendor_ota", cause=Cause.PEER_LAGGARD, tier=Tier.BREACH,
                      slc=Slice(Dimension.VENDOR, "Aarav Petrov Travel"))
    assert "Aarav Petrov Travel" in action_for(sliced)

    unsliced = _finding(metric_id="ota", cause=Cause.BELOW_TARGET, tier=Tier.CONCERN,
                        slc=Slice.all())
    action = action_for(unsliced)
    assert "{slice_value}" not in action
    assert action != ""


def test_low_confidence_says_fix_the_data_not_act_on_the_number():
    f = _finding(cause=Cause.LOW_CONFIDENCE, tier=Tier.WATCH)
    action = action_for(f)
    assert "fix" in action.lower() or "data" in action.lower()
    assert "escalate" not in action.lower()
    assert "review" not in action.lower()


def test_the_composer_output_contains_the_action_line_verbatim_for_a_breach():
    f = _finding(metric_id="vendor_ota", cause=Cause.PEER_LAGGARD, tier=Tier.BREACH)
    run = _run([f])
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert action_for(f) in brief


# ---------------------------------------------------------------------------
# Break-it-to-prove-it companions (documented in the task-8 report; these are
# the tests that would fail if the two breaks described in the plan were made).
# ---------------------------------------------------------------------------

def test_action_for_never_returns_the_raw_unformatted_template():
    f = _finding(metric_id="vendor_ota", cause=Cause.PEER_LAGGARD, tier=Tier.BREACH,
                slc=Slice(Dimension.VENDOR, "Aarav Petrov Travel"))
    assert "{slice_value}" not in action_for(f)


# ---------------------------------------------------------------------------
# Wiring: _action_sentence, _findings_as_text, _SYSTEM_PROMPT
# ---------------------------------------------------------------------------

def test_action_sentence_uses_action_for_when_non_empty():
    f = _finding(metric_id="vendor_ota", cause=Cause.PEER_LAGGARD, tier=Tier.BREACH,
                slc=Slice(Dimension.VENDOR, "Aarav Petrov Travel"))
    sentence = _action_sentence(f)
    assert action_for(f) in sentence


def test_findings_as_text_includes_the_action_line_per_finding():
    f = _finding(metric_id="vendor_ota", cause=Cause.PEER_LAGGARD, tier=Tier.BREACH)
    run = _run([f])
    text = _findings_as_text(run, Audience.TRANSPORT_MANAGER)
    assert "action:" in text
    assert action_for(f) in text


def test_system_prompt_tells_the_model_to_reproduce_the_action_not_invent_one():
    assert "Each finding carries an action." in _SYSTEM_PROMPT
    assert "Reproduce its meaning in your closing sentence." in _SYSTEM_PROMPT
    assert "Do not invent an action that is not there." in _SYSTEM_PROMPT
