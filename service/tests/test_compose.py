"""compose.py: the template brief and the Sarvam-validated brief.

Built against real Finding/Reference dataclasses (Controller ruling, task-6)
rather than fake dicts -- Task 4 exists, so there is no reason to fake them.
"""
from __future__ import annotations

import pytest

from signaldesk.compose import (_SYSTEM_PROMPT, _findings_as_text, sarvam_brief,
                                template_brief, validate_narrative)
from signaldesk.model import SarvamClient, TruncatedResponse
from signaldesk.schemas import (Audience, Cause, Dimension, FeedHealth, Finding,
                                Reference, ReferenceKind, Slice, Tier, Window,
                                finding_id)
from signaldesk.sweep import SweepRun

WINDOW = Window(1_000_000_000_000, 1_000_604_800_000)


def _finding(metric_id="vendor_ota", slc=None, observed=61.4, refs=None,
            tier=Tier.BREACH, cause=Cause.PEER_LAGGARD, gap=25.0, confidence=0.95,
            audiences=frozenset({Audience.TRANSPORT_MANAGER, Audience.FACILITIES_HEAD}),
            recurrence=None):
    slc = slc if slc is not None else Slice(Dimension.VENDOR, "Aarav Petrov Travel")
    refs = refs if refs is not None else (
        Reference(ReferenceKind.TREND, 55.0, "4-week average"),
        Reference(ReferenceKind.PEER, 60.0, "peer median"))
    return Finding(finding_id(metric_id, slc, WINDOW), metric_id, slc, WINDOW, observed,
                  refs, tier, cause, gap, confidence, audiences,
                  f"SELECT observed FROM trips WHERE trip_id = 'evidence-only-{metric_id}'",
                  recurrence=recurrence)


def _run(findings, feed_health=None, safety_alert_count=0, safety_alert_escort_pct=0.0):
    feed_health = feed_health if feed_health is not None else {
        "trips": FeedHealth("trips", 10_000, 100, 10, 5, 0.98),
    }
    return SweepRun("run-test", WINDOW, tuple(findings), feed_health, WINDOW.end_ms,
                    "week", safety_alert_count, safety_alert_escort_pct)


# ---------------------------------------------------------------------------
# template_brief
# ---------------------------------------------------------------------------

def test_the_template_cites_the_reference_point_for_every_claim():
    run = _run([_finding()])
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert "4-week average" in brief
    assert "peer median" in brief


def test_the_safety_line_appears_for_facilities_head_and_transport_manager():
    run = _run([_finding()], safety_alert_count=428, safety_alert_escort_pct=7.9)
    for audience in (Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER):
        brief = template_brief(run, audience)
        assert "WOMAN_TRAVELLING_ALONE" in brief
        assert "428" in brief
        assert "7.9" in brief


def test_the_safety_line_is_omitted_when_no_alert_fired():
    run = _run([_finding()], safety_alert_count=0)
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)
    assert "WOMAN_TRAVELLING_ALONE" not in brief


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
# Marshal diversity cap: one metric cannot fill the whole brief.
# ---------------------------------------------------------------------------

def test_a_dominant_metric_is_capped_at_three_per_brief():
    # Controller ruling: 20 marshal_compliance BREACHes + 3 ota CONCERNs
    # must yield 3 marshal + 3 ota lines, marshal first (marshal outranks
    # ota by tier, so it is already first in rank order).
    marshal_findings = [
        _finding(metric_id="marshal_compliance", cause=Cause.BELOW_TARGET, tier=Tier.BREACH,
                slc=Slice(Dimension.VENDOR, f"Vendor {i}"), gap=50.0 + i)
        for i in range(20)
    ]
    ota_findings = [
        _finding(metric_id="ota", cause=Cause.PEER_LAGGARD, tier=Tier.CONCERN,
                slc=Slice(Dimension.VENDOR, f"OTA Vendor {i}"), gap=10.0 + i)
        for i in range(3)
    ]
    run = _run(marshal_findings + ota_findings)
    brief = template_brief(run, Audience.TRANSPORT_MANAGER)

    marshal_lines = brief.count("Marshal compliance")
    ota_lines = brief.count("On-time arrival")
    assert marshal_lines == 3
    assert ota_lines == 3
    # marshal first: its first mention must precede ota's first mention.
    assert brief.index("Marshal compliance") < brief.index("On-time arrival")


# ---------------------------------------------------------------------------
# Task 16: recurrence -- template_brief's " (recurring, k/of weeks)" suffix
# and _findings_as_text's "recurring: k/of" line for the model prompt.
# ---------------------------------------------------------------------------

def test_template_brief_flags_a_recurring_finding_and_not_a_fresh_one():
    recurring = _finding(recurrence=(3, 4))
    fresh = _finding(recurrence=(1, 4), slc=Slice(Dimension.VENDOR, "Anand Fleet Services"))

    brief_recurring = template_brief(_run([recurring]), Audience.TRANSPORT_MANAGER)
    brief_fresh = template_brief(_run([fresh]), Audience.TRANSPORT_MANAGER)

    assert "(recurring, 3/4 weeks)" in brief_recurring
    assert "recurring" not in brief_fresh.lower()


def test_findings_as_text_includes_recurring_line_only_at_the_threshold():
    recurring = _finding(recurrence=(4, 4))
    fresh = _finding(recurrence=(2, 4), slc=Slice(Dimension.VENDOR, "Anand Fleet Services"))
    never_computed = _finding(recurrence=None, slc=Slice(Dimension.VENDOR, "Isha Mikhailov Travel"))

    text_recurring = _findings_as_text(_run([recurring]), Audience.TRANSPORT_MANAGER)
    text_fresh = _findings_as_text(_run([fresh]), Audience.TRANSPORT_MANAGER)
    text_never = _findings_as_text(_run([never_computed]), Audience.TRANSPORT_MANAGER)

    assert "recurring: 4/4" in text_recurring
    assert "recurring:" not in text_fresh
    assert "recurring:" not in text_never


def test_validator_accepts_recurrence_weeks_and_of_at_zero_decimal_places():
    # Task 16: only an integer IMMEDIATELY followed by a unit is checked at
    # all (a bare "4th"/"out of 4" is already exempt, unit or not) -- this
    # narrative deliberately writes the recurrence count in that
    # unit-suffixed shape ("4%") so the test actually exercises the new
    # allowed-set entry rather than a case the validator already ignored.
    # None of this finding's own values (observed 61.4, gap 25.0, confidence
    # 0.95, refs 55.0/60.0) round to 4 at 0dp, so this "4%" only passes
    # because recurrence.weeks/.of (4, 4) were added to allowed_0dp.
    f = _finding(recurrence=(4, 4))
    run = _run([f])
    narrative = ("Vendor on-time share is 61.40%, below the 4-week average of "
                "55.00% and the peer median of 60.00%; flagged 4% for repeat review.")
    assert validate_narrative(narrative, run) is None

    # Break-it-to-prove-it companion: without any recurrence attached, the
    # identical "4%" claim IS rejected -- proving the pass above came from
    # the recurrence entries, not some other coincidental allowance.
    f_no_recurrence = _finding(recurrence=None)
    run_no_recurrence = _run([f_no_recurrence])
    assert validate_narrative(narrative, run_no_recurrence) == "4"


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


# ---------------------------------------------------------------------------
# Fix-wave C1: a fabricated INTEGER (no decimal point) carrying a unit used
# to slip straight past the old decimals-only regex.
# ---------------------------------------------------------------------------

def test_the_validator_rejects_a_fabricated_integer_percentage():
    run = _run([_finding(observed=10.5,
                        refs=(Reference(ReferenceKind.PEER, 75.8, "peer median"),))])
    narrative = "On-time arrival is 78%, against a peer median of 91%."
    assert validate_narrative(narrative, run) == "78", (
        "an integer percentage with no decimal point must still be checked "
        "against the findings, not silently exempted")


# ---------------------------------------------------------------------------
# Opus review, second pass: prefix-position currency units.
# ---------------------------------------------------------------------------

def test_the_validator_catches_a_fabricated_figure_with_a_prefix_rupee_symbol():
    run = _run([_finding(metric_id="cost_per_km", observed=86.48,
                        refs=(Reference(ReferenceKind.PEER, 90.0, "peer median"),))])
    for narrative in ("Cost per km is ₹1,200 against a peer median of ₹90.",
                     "Cost per km is Rs 1200 against a peer median of Rs 90.",
                     "Cost per km is Rs. 1200 against a peer median of Rs. 90.",
                     "Cost per km is INR 1200 against a peer median of INR 90."):
        bad = validate_narrative(narrative, run)
        assert bad is not None, f"prefix-unit figure must be checked: {narrative!r}"


def test_the_validator_accepts_a_genuine_prefix_rupee_figure():
    run = _run([_finding(metric_id="cost_per_km", observed=86.0,
                        refs=(Reference(ReferenceKind.PEER, 90.0, "peer median"),))])
    narrative = "Cost per km is Rs 86 against a peer median of Rs 90."
    assert validate_narrative(narrative, run) is None


def test_the_validator_reads_the_full_comma_grouped_number_not_just_the_suffix():
    # The old bug: "1,200%" yielded just "200" (the regex stopped at the
    # comma), which could accept a fabricated 1,200% by matching a genuine 200.
    run = _run([_finding(observed=61.4)])
    narrative = "On-time arrival is 1,200% this week."
    assert validate_narrative(narrative, run) == "1,200"


def test_the_validator_accepts_an_integer_percentage_that_rounds_correctly():
    run = _run([_finding(observed=10.5,
                        refs=(Reference(ReferenceKind.PEER, 75.8, "peer median"),))])
    narrative = "On-time arrival is 10%, against a peer median of 76%."
    assert validate_narrative(narrative, run) is None


def test_the_validator_still_exempts_a_bare_count_with_no_unit():
    run = _run([_finding(observed=10.5,
                        refs=(Reference(ReferenceKind.PEER, 75.8, "peer median"),))])
    narrative = "8 findings this week; on-time arrival is 10%, against a peer median of 76%."
    assert validate_narrative(narrative, run) is None


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
    """`text`/`raises` behave every call (for a permanent failure or a
    guaranteed success). `sequence`, if given, is a list of (text, raises)
    pairs consumed one per call -- for `test_...retries_once_on_truncation`,
    where the first call must truncate and the second must succeed."""

    def __init__(self, text=None, raises=None, sequence=None):
        self.text = text
        self.raises = raises
        self.sequence = list(sequence) if sequence is not None else None
        self.calls = 0
        self.last_messages = None
        self.max_tokens_per_call = []

    def complete(self, messages, purpose="brief", max_tokens=None):
        self.calls += 1
        self.last_messages = messages
        self.max_tokens_per_call.append(max_tokens)
        text, raises = (self.sequence.pop(0) if self.sequence
                       else (self.text, self.raises))
        if raises is not None:
            raise raises
        return text


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


def test_the_prompt_carries_at_most_eight_findings():
    # On the real dataset one audience can carry 150+ findings; the prompt
    # must cap at the same top-8 the template shows, never send them all.
    # Four DIFFERENT metrics (3 each) so the marshal-diversity cap (at most
    # 3 per metric) does not itself reduce this below 8 -- that cap has its
    # own dedicated test above.
    metric_ids = ["vendor_ota", "ota", "otd", "no_show_rate"]
    findings = [
        _finding(metric_id=metric_ids[i % 4], slc=Slice(Dimension.VENDOR, f"Vendor {i}"))
        for i in range(12)
    ]
    run = _run(findings)
    model = StubModel(text="placeholder narrative, not validated by this test")
    sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=model)
    prompt_text = model.last_messages[1]["content"]
    finding_lines = [line for line in prompt_text.splitlines() if line.startswith("[")]
    assert len(finding_lines) == 8


def test_one_call_on_success_at_most_two_on_truncation():
    # The cost story from model.py's CostMeter docstring, updated: success
    # costs one model call, same as before. A truncated first attempt costs
    # a second -- never more (see compose._call_with_retry) -- because
    # sarvam-105b's reasoning overhead is measured to be unbounded-variable,
    # so a single fixed ceiling cannot be trusted to never truncate.
    run = _run([_finding()])
    good_text = ("Vendor on-time share is 61.40%, below the 4-week average of "
                "55.00% and the peer median of 60.00%. Action: review.")

    success_model = StubModel(text=good_text)
    sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=success_model)
    assert success_model.calls == 1

    retry_model = StubModel(sequence=[
        (None, TruncatedResponse("hit the ceiling", prompt_tokens=543,
                                 completion_tokens=6000, max_tokens=6000)),
        (good_text, None),
    ])
    brief = sarvam_brief(run, Audience.TRANSPORT_MANAGER, model=retry_model)
    assert retry_model.calls == 2
    assert "61.40" in brief
    # the retry asked for double the ceiling that was hit
    assert retry_model.max_tokens_per_call == [None, 12000]


def test_the_system_prompt_forbids_cross_slice_causation_and_citation_markers():
    # Two Sarvam-narrative defects seen on real data: claiming one finding
    # CAUSES another across unrelated slices, and writing bracketed citation
    # markers ("[1]") with no footnote key. Cheap guard against a later
    # prompt edit silently dropping either instruction.
    assert ("Do not claim that one finding causes another unless the findings "
           "themselves establish it") in _SYSTEM_PROMPT
    assert "causation across different slices" in _SYSTEM_PROMPT
    assert "Do not use citation markers such as [1]; write plain prose." in _SYSTEM_PROMPT


def test_the_default_token_ceiling_leaves_room_for_reasoning_overhead():
    # MEASURED 2026-09-05, 5 real calls on data/real at max_tokens=16000, same
    # 8-finding TRANSPORT_MANAGER prompt: completion_tokens 10545, 2096,
    # 15427, 8686, 9293 -- min 2096, max 15427, ALL finish_reason=stop, but
    # one at 96% of the ceiling. The overhead is unbounded-variable and
    # task-dependent, not a fixed multiple of prompt size (see model.py's
    # full measurement log) -- this floor is a generous ceiling given that
    # spread, not a guarantee; compose._call_with_retry's one retry at double
    # the ceiling is what actually protects the tail.
    assert SarvamClient.DEFAULT_MAX_TOKENS >= 14000


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
