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

def test_exactly_five_tools_and_none_named_for_raw_sql():
    names = {t["function"]["name"] for t in tools.TOOL_SCHEMAS}
    assert len(tools.TOOL_SCHEMAS) == 5
    assert names == {"list_metrics", "get_metric", "list_findings",
                     "explain_finding", "decompose_finding"}
    assert "run_sql" not in names
    assert not any("sql" in n.lower() for n in names)


def test_build_tools_exposes_the_same_five_names():
    con = duckdb.connect()
    impl = tools._build_tools(con, _run([_finding()]))
    assert set(impl) == {"list_metrics", "get_metric", "list_findings",
                         "explain_finding", "decompose_finding"}
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


def test_the_loop_stops_at_four_tool_calls():
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
