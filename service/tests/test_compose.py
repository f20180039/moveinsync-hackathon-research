"""compose.py: the template brief and the Sarvam-validated brief.

Built against real Finding/Reference dataclasses (Controller ruling, task-6)
rather than fake dicts -- Task 4 exists, so there is no reason to fake them.
"""
from __future__ import annotations

import pytest

from signaldesk.compose import sarvam_brief, template_brief, validate_narrative
from signaldesk.model import SarvamClient, TruncatedResponse
from signaldesk.schemas import (Audience, Cause, Dimension, FeedHealth, Finding,
                                Reference, ReferenceKind, Slice, Tier, Window,
                                finding_id)
from signaldesk.sweep import SweepRun

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
# template_brief
# ---------------------------------------------------------------------------

def test_the_template_cites_the_reference_point_for_every_claim():
    run = _run([_finding()])
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert "4-week average" in brief
    assert "peer median" in brief


def test_the_template_mentions_confidence_only_when_below_nine_tenths():
    low = _finding(confidence=0.72)
    high = _finding(confidence=0.95)
    brief_low = template_brief(_run([low]), Audience.TRANSPORT_MANAGER)
    brief_high = template_brief(_run([high]), Audience.TRANSPORT_MANAGER)
    assert "confidence" in brief_low
    assert "confidence" not in brief_high


def test_the_template_introduces_no_figure_absent_from_the_findings():
    run = _run([_finding()])
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert validate_narrative(brief, run) is None


def test_it_produces_an_honest_brief_when_nothing_is_wrong():
    passing = _finding(tier=Tier.PASS, cause=Cause.ON_REFERENCE, gap=0.0)
    run = _run([passing])
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert "Nothing above PASS" in brief
    assert "[PASS]" not in brief


# ---------------------------------------------------------------------------
# validate_narrative
# ---------------------------------------------------------------------------

def test_the_validator_accepts_a_narrative_whose_every_figure_is_in_the_findings():
    run = _run([_finding()])
    narrative = ("Vendor on-time share is 61.40%, below the 4-week average of "
                "55.00% and the peer median of 60.00%.")
    assert validate_narrative(narrative, run) is None


def test_the_validator_rejects_an_invented_figure():
    run = _run([_finding()])
    narrative = "Vendor on-time share is 99.99%, a number nowhere in the findings."
    assert validate_narrative(narrative, run) == "99.99"


def test_the_validator_rejects_a_figure_that_is_close_but_not_equal_to_two_places():
    run = _run([_finding(observed=61.4)])
    narrative = "Vendor on-time share is 61.42%."
    assert validate_narrative(narrative, run) == "61.42"


def test_the_validator_ignores_dates_and_integers_that_are_not_metric_claims():
    run = _run([_finding()])
    narrative = "As of 2026-09-04, 3 vendors were reviewed this week."
    assert validate_narrative(narrative, run) is None


def test_the_validator_tolerates_trailing_zero_differences():
    run = _run([_finding(observed=61.4)])
    narrative = "Vendor on-time share is 61.40%."
    assert validate_narrative(narrative, run) is None


def test_the_validator_accepts_every_number_the_template_itself_renders():
    # Proves the coupling: template_brief and validate_narrative both format
    # through compose._rendered, so a number the template writes can never
    # fail its own validator -- even with awkward, non-round true values, one
    # rendered at 1dp (a percentage) and one at 2dp (a rupee figure).
    pct_finding = _finding(
        metric_id="vendor_ota", observed=33.333,
        refs=(Reference(ReferenceKind.TREND, 55.111, "4-week average"),
             Reference(ReferenceKind.PEER, 60.222, "peer median")))
    inr_finding = _finding(
        metric_id="cost_per_km", observed=144.165,
        slc=Slice(Dimension.SITE, "Eastgate Office"),
        refs=(Reference(ReferenceKind.TREND, 130.456, "4-week average"),
             Reference(ReferenceKind.PEER, 128.789, "peer median")))
    run = _run([pct_finding, inr_finding])

    for audience in (Audience.TRANSPORT_MANAGER, Audience.FACILITIES_HEAD):
        brief = template_brief(run, audience)
        assert validate_narrative(brief, run) is None


# ---------------------------------------------------------------------------
# sarvam_brief
# ---------------------------------------------------------------------------

class StubModel:
    def __init__(self, text=None, raises=None):
        self.text = text
        self.raises = raises
        self.calls = 0
        self.last_messages = None

    def complete(self, messages, purpose="brief", max_tokens=None):
        self.calls += 1
        self.last_messages = messages
        if self.raises is not None:
            raise self.raises
        return self.text


def test_sarvam_brief_substitutes_the_template_when_the_model_invents_a_figure():
    run = _run([_finding()])
    model = StubModel(text="Vendor on-time share is a shocking 12.34% this week.")
    brief = sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=model)
    assert "[BREACH]" in brief
    assert "12.34" not in brief


def test_sarvam_brief_substitutes_the_template_when_the_model_is_unreachable():
    run = _run([_finding()])
    model = StubModel(raises=RuntimeError("connection refused"))
    brief = sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=model)
    assert "[BREACH]" in brief


def test_sarvam_brief_substitutes_the_template_when_the_model_truncates():
    # A half-written brief whose figures are all correct PASSES the numeric
    # validator. Truncation has to be caught before validation, not by it.
    run = _run([_finding()])
    model = StubModel()
    model.raises = TruncatedResponse("brief hit the ceiling")
    brief = sarvam_brief(run, Audience.FACILITIES_HEAD, model=model)
    assert "[BREACH]" in brief          # the template's marker


def test_the_prompt_carries_findings_not_rows_and_no_sql():
    run = _run([_finding()])
    model = StubModel(text=("Vendor on-time share is 61.40%, below the 4-week average of "
                            "55.00% and the peer median of 60.00%. Action: raise on-time "
                            "performance with Aarav Petrov Travel before the next weekly "
                            "review."))
    sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=model)
    prompt_text = " ".join(m["content"] for m in model.last_messages)
    assert "trip_id" not in prompt_text
    assert "SELECT" not in prompt_text


def test_one_model_call_per_brief():
    run = _run([_finding()])
    model = StubModel(text=("Vendor on-time share is 61.40%, below the 4-week average of "
                            "55.00% and the peer median of 60.00%. Action: review."))
    sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=model)
    assert model.calls == 1


def test_the_default_token_ceiling_leaves_room_for_reasoning_overhead():
    # Measured: ~200 completion tokens of reasoning before any prose.
    # A 200-word brief is ~280 tokens of prose. 1600 leaves real headroom.
    assert SarvamClient.DEFAULT_MAX_TOKENS >= 1200


class _FakeChoice:
    def __init__(self, content, finish_reason):
        self.message = type("Msg", (), {"content": content})()
        self.finish_reason = finish_reason


class _FakeCompletion:
    def __init__(self, content, finish_reason, usage=None):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = usage


def test_sarvam_client_raises_truncated_response_when_the_model_hits_the_token_ceiling():
    # Extra direct coverage of model.py's own guard (no test names given for
    # model.py in the brief's list): the finish_reason=="length" check is the
    # only thing standing between a half-written brief and the numeric
    # validator, which cannot detect truncation on its own. No real network:
    # the underlying OpenAI client is swapped for a fake completions.create.
    client = SarvamClient(api_key="test-key-not-real")
    client._client.chat.completions.create = lambda **kwargs: _FakeCompletion(
        "Vendor on-time share is 6", "length")
    with pytest.raises(TruncatedResponse):
        client.complete([{"role": "user", "content": "hi"}], purpose="brief")


def test_sarvam_client_raises_truncated_response_when_content_is_empty():
    client = SarvamClient(api_key="test-key-not-real")
    client._client.chat.completions.create = lambda **kwargs: _FakeCompletion(
        "", "stop")
    with pytest.raises(TruncatedResponse):
        client.complete([{"role": "user", "content": "hi"}], purpose="brief")
