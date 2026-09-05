"""tools.py: the five validated tools and the bounded interrogator behind
POST /api/ask.

Built against real Finding dataclasses (same pattern as test_compose.py) and
a tiny synthetic `trips` table (same pattern as test_decompose.py) for the
one tool, decompose_finding, that needs a live connection.
"""
from __future__ import annotations

import duckdb
import pytest

from signaldesk import registry, tools
from signaldesk.model import TruncatedResponse
from signaldesk.schemas import (Audience, Cause, Dimension, FeedHealth, Finding,
                                Metric, Reference, ReferenceKind, Slice, Tier,
                                Window, finding_id, Direction)
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
                  f"evidence-only-{metric_id}")


def _run(findings):
    feed_health = {"trips": FeedHealth("trips", 10_000, 100, 10, 5, 0.98)}
    return SweepRun("run-test", WINDOW, tuple(findings), feed_health, WINDOW.end_ms)


# ---------------------------------------------------------------------------
# The invariant this task exists to prove: exactly five tools, none named
# for arbitrary SQL.
# ---------------------------------------------------------------------------

# Task 18b adds summarize_run (the grounded whole-week answer), so this is
# six now, not five. The invariant the name of this test is really about is
# unchanged and is the second half: NO tool hands the model raw SQL.
_TOOL_NAMES = {"list_metrics", "get_metric", "list_findings",
               "explain_finding", "decompose_finding", "summarize_run"}


def test_exactly_six_tools_and_none_named_for_raw_sql():
    names = {t["function"]["name"] for t in tools.TOOL_SCHEMAS}
    assert len(tools.TOOL_SCHEMAS) == 6
    assert names == _TOOL_NAMES
    assert "run_sql" not in names
    assert not any("sql" in n.lower() for n in names)


def test_build_tools_exposes_the_same_six_names():
    con = duckdb.connect()
    impl = tools._build_tools(con, _run([_finding()]))
    assert set(impl) == _TOOL_NAMES
    con.close()


# ---------------------------------------------------------------------------
# Argument validation BEFORE execution -- the enums already name the valid
# values; a tool just needs to not swallow that.
# ---------------------------------------------------------------------------

def test_get_metric_refuses_an_unknown_id_naming_the_valid_ones():
    with pytest.raises(ValueError, match="ota"):
        tools._get_metric("not_a_real_metric")


def test_list_findings_refuses_an_unknown_tier_naming_the_valid_ones():
    run = _run([_finding()])
    with pytest.raises(ValueError, match="BREACH"):
        tools._list_findings(run, tier="CATASTROPHIC")


def test_explain_finding_refuses_an_unknown_finding_id():
    run = _run([_finding()])
    with pytest.raises(ValueError, match="unknown finding"):
        tools._explain_finding(run, "no-such-finding-ever")


def test_decompose_finding_refuses_an_unknown_dimension_naming_the_valid_ones():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE trips (scheduled_at BIGINT, vendor_id VARCHAR, ok INTEGER)
    """)
    metric = Metric("vendor_ota", "Vendor on-time share", "%", Direction.HIGHER,
                    "SELECT 100.0*sum(ok)/nullif(count(*),0), count(*) AS n "
                    "FROM trips t WHERE t.scheduled_at >= ? AND t.scheduled_at < ? {{SLICE}}",
                    (ReferenceKind.TREND,), "trips", (), dims=(Dimension.VENDOR,))
    real_by_id = registry.by_id
    try:
        registry.by_id = lambda mid: metric if mid == "vendor_ota" else real_by_id(mid)
        run = _run([_finding(metric_id="vendor_ota")])
        with pytest.raises(ValueError, match="DELAY_REASON"):
            tools._decompose_finding(con, run, run.findings[0].id, "NOT_A_REAL_DIM")
    finally:
        registry.by_id = real_by_id
        con.close()
        registry.clear_cache()


def test_a_missing_required_argument_is_refused_not_defaulted():
    impl = tools._build_tools(duckdb.connect(), _run([_finding()]))
    with pytest.raises(TypeError):
        impl["get_metric"]()   # metric_id is required, no default


# ---------------------------------------------------------------------------
# The bounded interrogator loop.
# ---------------------------------------------------------------------------

class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class StubModel:
    """A scripted sequence of complete_message() returns (or exceptions),
    one per call, consumed in order."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0
        self.last_messages = None

    def complete_message(self, messages, tools=None, purpose="ask", max_tokens=None):
        self.calls += 1
        self.last_messages = messages
        item = self.sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_the_loop_stops_at_max_tool_calls():
    run = _run([_finding()])
    # Always asks for another tool call -- never answers -- to prove the
    # bound is enforced rather than trusted to the model's own good behaviour.
    always_calls = [
        _FakeMessage(tool_calls=[_FakeToolCall(f"c{i}", "list_metrics", "{}")])
        for i in range(10)
    ]
    model = StubModel(always_calls)
    result = tools.ask(duckdb.connect(), run, "keep going forever", model=model)
    assert result["withheld"] is True
    assert "budget" in result["reason"]
    assert model.calls == tools.MAX_TOOL_CALLS
    assert len(result["trace"]) == tools.MAX_TOOL_CALLS


def test_an_answer_containing_a_figure_no_tool_returned_is_withheld():
    run = _run([_finding(observed=61.4)])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "list_metrics", "{}")]),
        _FakeMessage(content="Vendor on-time share is a shocking 12.34% this week."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "how are we doing?", model=model)
    assert result["withheld"] is True
    assert result["answer"] is None
    assert "12.34" in result["reason"]
    assert len(result["trace"]) == 1   # the tool call still shows up


def test_an_answer_matching_a_tool_returned_figure_is_accepted():
    run = _run([_finding(metric_id="vendor_ota", observed=61.4)])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "list_findings", "{}")]),
        _FakeMessage(content="Vendor on-time share is 61.40% this week."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "how are we doing?", model=model)
    assert result["withheld"] is False
    assert result["answer"] == "Vendor on-time share is 61.40% this week."


def test_max_tool_calls_is_generous_but_still_bounded():
    # History, in order: 4 -> 3 as a perf fix (the loop made four round trips
    # where two would do, 42s measured on stage) -> 8 on explicit user
    # direction after live testing showed the headline demo question withheld
    # roughly two times in three with "tool call budget (3) exhausted".
    # Correctness over latency. The bound itself is load-bearing -- it must be
    # generous AND it must exist, so this asserts both ends.
    assert tools.MAX_TOOL_CALLS == 8
    assert isinstance(tools.MAX_TOOL_CALLS, int) and tools.MAX_TOOL_CALLS > 0


def test_the_budget_exhausted_refusal_path_is_still_intact():
    # A model that will not converge must stop and say so, not spin. Raising
    # the budget must not have turned the loop unbounded.
    run = _run([_finding()])
    model = StubModel([
        _FakeMessage(tool_calls=[_FakeToolCall(f"c{i}", "list_findings", "{}")])
        for i in range(tools.MAX_TOOL_CALLS + 5)
    ])
    result = tools.ask(duckdb.connect(), run, "keep going forever", model=model)
    assert result["withheld"] is True
    assert f"budget ({tools.MAX_TOOL_CALLS})" in result["reason"]
    assert model.calls == tools.MAX_TOOL_CALLS


def test_a_question_that_needs_four_calls_now_answers_instead_of_being_withheld():
    """The regression the raise exists for: at MAX_TOOL_CALLS = 3 this exact
    shape -- three tool calls, then an answer -- came back withheld with
    "tool call budget (3) exhausted"."""
    run = _run([_finding(metric_id="vendor_ota", observed=61.4)])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "list_findings", "{}")]),
        _FakeMessage(tool_calls=[_FakeToolCall("c2", "list_findings", "{}")]),
        _FakeMessage(tool_calls=[_FakeToolCall("c3", "list_findings", "{}")]),
        _FakeMessage(content="Vendor on-time share is 61.40% this week."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "which vendor is worst?", model=model)
    assert result["withheld"] is False, result["reason"]
    assert len(result["trace"]) == 3


# ---------------------------------------------------------------------------
# summarize_run -- the grounded whole-week answer. A user asked "provide a
# review of this week" and got withheld with "answer contained a figure no
# tool returned: 14.8": the validator was right, the model had nothing
# grounded to quote.
# ---------------------------------------------------------------------------

def test_summarize_run_returns_the_systems_own_composed_brief():
    from signaldesk.compose import template_brief
    from signaldesk.schemas import Audience
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    out = tools._summarize_run(run)
    assert out["audience"] == "TRANSPORT_MANAGER"
    assert out["windowLabel"] == run.window.label
    assert out["findingCount"] == len(run.findings)
    assert out["tierCounts"]["BREACH"] == 1
    # It is the SAME text the brief endpoint serves -- not a second
    # summarisation path written for the model's benefit.
    assert out["brief"] == template_brief(run, Audience.TRANSPORT_MANAGER)


def test_summarize_run_brief_passes_the_validator_it_will_be_quoted_through():
    """Every figure the tool hands over must be one the model is allowed to
    repeat -- otherwise this tool would set up the exact rejection it exists
    to prevent."""
    from signaldesk.compose import validate_narrative
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    out = tools._summarize_run(run)
    assert validate_narrative(out["brief"], run) is None


def test_summarize_run_omits_the_outlook_line_whose_figures_are_not_quotable():
    # forecast.py's projected figures are not finding values, so a model
    # quoting one would be correctly rejected. The tool must not hand over a
    # number the answer cannot survive repeating.
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    assert "outlook:" not in tools._summarize_run(run)["brief"]


def test_summarize_run_rejects_an_unknown_audience_naming_the_valid_ones():
    run = _run([_finding()])
    with pytest.raises(ValueError) as exc:
        tools._summarize_run(run, audience="CEO")
    assert "TRANSPORT_MANAGER" in str(exc.value)


def test_summarize_run_is_registered_as_a_tool_the_model_can_actually_call():
    names = [t["function"]["name"] for t in tools.TOOL_SCHEMAS]
    assert "summarize_run" in names
    run = _run([_finding()])
    assert "summarize_run" in tools._build_tools(duckdb.connect(), run)


def test_a_week_review_answer_quoting_the_summary_is_accepted():
    """End to end through ask(): the tool result's figures reach the validator
    as extra_values, so a week review built from them is NOT withheld."""
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "summarize_run", "{}")]),
        _FakeMessage(content="One finding breached this week: vendor on-time "
                             "share at 61.40%."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "provide a review of this week", model=model)
    assert result["withheld"] is False, result["reason"]
    assert result["trace"][0]["tool"] == "summarize_run"


def test_the_invented_figure_guardrail_is_unweakened_by_the_new_tool():
    """The user's bug was a made-up 14.8. summarize_run gives the model a
    grounded alternative -- it must NOT make an invented figure acceptable."""
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "summarize_run", "{}")]),
        _FakeMessage(content="On-time arrival averaged 14.8% across the week."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "provide a review of this week", model=model)
    assert result["withheld"] is True
    assert "14.8" in result["reason"]


def test_the_digest_carries_metric_and_finding_ids_so_no_call_is_spent_finding_them():
    # Live testing showed calls burnt on list_metrics purely to learn an id
    # the digest could have named.
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    digest = tools._context_digest(run)
    assert "metric_id=vendor_ota" in digest
    assert f"finding_id={run.findings[0].id}" in digest


def test_the_system_prompt_is_primed_with_the_runs_own_top_findings():
    # Perf fix: the common question should be answerable with zero tool
    # calls once the digest is in the system prompt.
    run = _run([_finding(metric_id="vendor_ota", observed=61.4, tier=Tier.BREACH)])
    model = StubModel([_FakeMessage(content="Vendor on-time share is 61.40% this week.")])
    result = tools.ask(duckdb.connect(), run, "how are we doing?", model=model)
    assert result["withheld"] is False
    assert len(result["trace"]) == 0, "the digest should answer this without a tool call"
    system_content = model.last_messages[0]["content"]
    assert "Vendor on-time share" in system_content
    assert "61.40" in system_content


def test_a_tool_that_raises_is_reported_in_the_trace_not_a_failed_request():
    run = _run([_finding()])
    sequence = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "get_metric", "{}")]),   # missing metric_id
        _FakeMessage(content="I could not verify that."),
    ]
    model = StubModel(sequence)
    result = tools.ask(duckdb.connect(), run, "tell me about metric x", model=model)
    assert len(result["trace"]) == 1
    assert "error" in result["trace"][0]["result"]
    # the request itself still completes -- the tool's failure is reported,
    # not raised.
    assert result["withheld"] in (True, False)


def test_a_model_outage_returns_a_plain_refusal_with_a_trace():
    run = _run([_finding()])
    model = StubModel([RuntimeError("connection refused")])
    result = tools.ask(duckdb.connect(), run, "anything", model=model)
    assert result["answer"] is None
    assert result["withheld"] is True
    assert result["reason"]
    assert result["trace"] == []


def test_no_api_key_returns_a_plain_refusal_without_calling_the_model(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    run = _run([_finding()])
    result = tools.ask(duckdb.connect(), run, "anything", model=None)
    assert result["answer"] is None
    assert result["withheld"] is True
    assert "SARVAM_API_KEY" in result["reason"]
    assert result["trace"] == []


def test_a_truncated_response_twice_is_withheld():
    run = _run([_finding()])
    model = StubModel([
        TruncatedResponse("hit the ceiling", max_tokens=8000),
    ])
    # complete_message itself would normally retry internally via
    # _complete_with_retry; simulate both attempts truncating by having the
    # stub itself raise on the ONE call tools.ask makes per loop iteration
    # (ask's own retry lives in _complete_with_retry, which calls
    # model.complete_message twice in that case -- exhaust the sequence).
    model.sequence = [
        TruncatedResponse("hit the ceiling", max_tokens=8000),
        TruncatedResponse("hit the ceiling again", max_tokens=16000),
    ]
    result = tools.ask(duckdb.connect(), run, "anything", model=model)
    assert result["withheld"] is True
    assert "truncated" in result["reason"]


# ---------------------------------------------------------------------------
# Provenance -- UAT task 1. "When the console shows output after the LLM
# call, is it really using Gen AI?" was tribal knowledge: the brief already
# carried `source` ("sarvam" | "template") but /api/ask carried nothing, so
# an answer on screen could not be told apart from a refusal-shaped
# deterministic path by anyone reading the response. Every ask result now
# names the path that produced it, honestly, in the same vocabulary.
# ---------------------------------------------------------------------------

def test_an_accepted_answer_is_labelled_as_coming_from_the_model():
    run = _run([_finding()])
    model = StubModel([_FakeMessage(content="Vendor is behind its peers.")])
    result = tools.ask(duckdb.connect(), run, "anything", model=model)
    assert result["withheld"] is False
    assert result["source"] == tools.SOURCE_MODEL == "sarvam"


def test_a_withheld_answer_is_labelled_as_not_coming_from_the_model():
    # Every refusal path must be honest about the same thing: nothing the
    # model wrote reached the screen. Four of them, one per exit.
    run = _run([_finding()])
    outage = tools.ask(duckdb.connect(), run, "anything",
                       model=StubModel([RuntimeError("connection refused")]))
    empty = tools.ask(duckdb.connect(), run, "anything",
                      model=StubModel([_FakeMessage(content="")]))
    invented = tools.ask(duckdb.connect(), run, "anything",
                         model=StubModel([_FakeMessage(content="OTA was 12.7%.")]))
    truncated = tools.ask(duckdb.connect(), run, "anything", model=StubModel([
        TruncatedResponse("hit the ceiling", max_tokens=8000),
        TruncatedResponse("hit it again", max_tokens=16000)]))
    for result in (outage, empty, invented, truncated):
        assert result["withheld"] is True
        assert result["source"] == tools.SOURCE_WITHHELD == "withheld"


def test_no_api_key_is_labelled_withheld_not_silently_answered(monkeypatch):
    # The single most misleading case: no key configured at all. The answer
    # must not merely be null -- it must SAY that no model produced it.
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    run = _run([_finding()])
    result = tools.ask(duckdb.connect(), run, "anything", model=None)
    assert result["source"] == tools.SOURCE_WITHHELD


def test_the_budget_exhausted_refusal_is_also_labelled():
    run = _run([_finding()])
    model = StubModel([_FakeMessage(tool_calls=[
        _FakeToolCall(f"c{i}", "list_metrics", "{}")]) for i in range(tools.MAX_TOOL_CALLS)])
    result = tools.ask(duckdb.connect(), run, "anything", model=model)
    assert result["withheld"] is True
    assert result["source"] == tools.SOURCE_WITHHELD
