"""The four -- now five -- validated tools, and the bounded interrogator
behind `POST /api/ask`.

There is no tool that hands the model a raw query. That is the deliberate
difference between this and a text-to-SQL demo: every tool here is a narrow,
named question this system already knows how to answer correctly (via
registry.py/decompose.py), never an open door to arbitrary SQL the model
could get wrong (test_invariant.py greps for the literal tool name this
paragraph is carefully not spelling out, and for the raw-query keyword,
across every module in this package). Arguments are
validated against the enumerations BEFORE execution -- `Dimension.parse` and
`registry.by_id` already raise with the valid values named, so a tool catches
that and returns it as the tool's own result (visible in the trace) rather
than re-implementing validation or letting a bad argument reach a query.

No SQL here at all (spec 1.1) -- every tool reaches data through registry.py/
decompose.py/sweep.py's own functions.
"""
from __future__ import annotations

import json
import logging
import os

from . import registry
from .actions import action_for
from .compose import template_brief, validate_narrative
from .decompose import decompose as decompose_finding_rows
from .decompose import valid_dims
from .model import SarvamClient, TruncatedResponse
from .schemas import Audience, Finding, Tier

logger = logging.getLogger("signaldesk")

# Perf fix (42s measured on stage -- too slow to click live): three changes,
# together, not any one alone. (1) MAX_TOOL_CALLS 4 -> 3: the loop was making
# four round trips where two would do. (2) the system prompt is now PRIMED
# with a digest of the run's own top findings (the same shape
# compose._findings_as_text builds) so the common question is answerable
# with zero or one tool call instead of discovering the same ground via
# list_metrics + list_findings every time. (3) ASK_MAX_TOKENS 8000 -> 4000 --
# most of the 42s was reasoning tokens, not tool round trips.
#
# SUPERSEDED for the budget alone (live testing, 2026-09-05, controller +
# explicit user direction). (2) and (3) above stand and are untouched; only
# the 4 -> 3 in (1) is reversed, and further, to 8.
#
# What the 3 actually cost: tested live against data/sample, the headline
# demo question ("Which vendor is worst on on-time arrival, and what should
# I do about it?") came back WITHHELD roughly two times in three, reason
# "tool call budget (3) exhausted". Observed traces:
# [list_findings, explain_finding, explain_finding] (withheld),
# [list_metrics, list_findings] (answered),
# [list_metrics, list_findings, list_findings] (withheld). The bound was not
# cutting wasted round trips -- it was cutting the answer off mid-work, and
# a refusal on the headline question is worth far less than the seconds it
# saved. The user's direction is explicit: "Don't worry about the token
# budget, keep it generous."
#
# 8, not unbounded. The loop is still hard-bounded and the
# budget-exhausted refusal below is still the honest exit when it genuinely
# runs out -- a model that will not converge must stop, not spin. The prompt
# still asks for the fewest calls that answer the question; the difference
# is that asking is now a preference rather than a cliff.
MAX_TOOL_CALLS = 8
ASK_MAX_TOKENS = 4000
# The one retry tools.py allows on a truncated turn, at double the ceiling
# that was hit -- same reasoning as compose._call_with_retry, capped lower
# here since ask latency is what a judge waits on live, on stage.
ASK_MAX_RETRY_TOKENS = 16_000

_SYSTEM_PROMPT_TEMPLATE = (
    "You are Signal Desk's interrogator, answering one question about a "
    "completed sweep. Below is a digest of the run's own top findings, "
    "already tiered, ranked and referenced -- answer from this digest FIRST, "
    "with NO tool call, whenever it already contains what the question "
    "needs:\n{digest}\n\n"
    "If the digest is not enough, use the tools you are given -- "
    "summarize_run, list_findings, explain_finding, decompose_finding, "
    "get_metric, list_metrics -- and prefer the FEWEST calls that answer the "
    "question. Apply the tier/metric_id filters you need on the first "
    "list_findings call rather than calling it repeatedly. Do NOT call "
    "list_metrics: the digest above already names every metric in play, and "
    "each finding id carries its own metric id. For a whole-week question "
    "-- \"review this week\", \"how did we do\", \"summarise the run\" -- "
    "call summarize_run ONCE and answer from its brief and tier counts; do "
    "not assemble a week review out of individual findings and do not work "
    "out a total yourself. Never compute, estimate, or recall a figure "
    "yourself; every "
    "number in your answer must come from the digest above or a tool "
    "result. If the question asks for a forecast or prediction (e.g. \"what "
    "will OTA be next month\"), or anything none of the tools can answer, "
    "decline and say plainly what you checked instead of guessing. Do not "
    "claim that one finding causes another unless the digest or tool "
    "results themselves establish it -- describe co-occurring conditions, "
    "never causation across different slices. Do not use citation markers "
    "such as [1]; write plain prose."
)


# ---------------------------------------------------------------------------
# Tool implementations. Each raises ValueError (with valid values named,
# where the enum already does that) on a bad argument rather than guessing;
# the interrogator loop catches it and reports it in the trace as this
# tool's own result.
# ---------------------------------------------------------------------------

def _finding_summary(f: Finding) -> dict:
    metric = registry.by_id(f.metric_id)
    return {
        "id": f.id,
        "metricId": f.metric_id,
        "metricLabel": metric.label,
        "sliceLabel": f.slice.label,
        "tier": f.tier.name,
        "cause": f.cause.value,
        "observed": round(f.observed, 2),
        "gap": round(f.gap, 2),
        "references": [{"kind": r.kind.value, "value": round(r.value, 2), "label": r.label}
                       for r in f.refs],
    }


def _find(run, finding_id: str) -> Finding:
    for f in run.findings:
        if f.id == finding_id:
            return f
    raise ValueError(f"unknown finding id {finding_id!r} in this run")


def _list_metrics() -> dict:
    return {
        "metrics": [
            {"id": m.id, "label": m.label, "unit": m.unit, "better": m.better.value,
             "dims": [d.name for d in m.dims]}
            for m in registry.METRICS
        ]
    }


def _get_metric(metric_id: str) -> dict:
    m = registry.by_id(metric_id)   # raises ValueError naming the valid ids
    return {
        "id": m.id, "label": m.label, "unit": m.unit, "better": m.better.value,
        "refs": [r.value for r in m.refs], "target": m.target, "hardTarget": m.hard_target,
        "dims": [d.name for d in m.dims],
    }


def _list_findings(run, metric_id: str | None = None, tier: str | None = None,
                   limit: int = 20) -> dict:
    findings = list(run.findings)
    if metric_id is not None:
        registry.by_id(metric_id)   # validate before filtering; raises with valid ids
        findings = [f for f in findings if f.metric_id == metric_id]
    if tier is not None:
        try:
            t = Tier[tier.upper()]
        except KeyError:
            valid = ", ".join(t.name for t in Tier)
            raise ValueError(f"unknown tier {tier!r}; valid values are {valid}")
        findings = [f for f in findings if f.tier is t]
    limit = max(1, min(int(limit), 50))
    return {"findings": [_finding_summary(f) for f in findings[:limit]]}


def _explain_finding(run, finding_id: str) -> dict:
    f = _find(run, finding_id)
    return {
        **_finding_summary(f),
        "action": action_for(f),
        "confidence": round(f.confidence, 2),
        "evidenceSql": f.evidence_sql,
        "owns": [{"value": v, "pointsOfGap": round(p, 2), "n": n} for v, p, n in f.owns],
    }


def _decompose_finding(con, run, finding_id: str, dim: str) -> dict:
    f = _find(run, finding_id)
    rows = decompose_finding_rows(con, f, dim)   # raises ValueError naming the valid dims
    return {
        "findingId": f.id,
        "dim": dim.upper(),
        "rows": [
            {"value": r["value"], "observed": r["observed"] if r["observed"] is None
                                    else round(r["observed"], 2),
             "shareOfVolume": round(r["share_of_volume"], 4),
             "pointsOfGap": round(r["points_of_gap"], 2), "n": r["n"]}
            for r in rows
        ],
    }


def _summarize_run(run, audience: str | None = None) -> dict:
    """The SETTLED week summary -- Task 18b.

    A user asked "provide a review of this week" and the answer was withheld
    with "answer contained a figure no tool returned: 14.8". The validator
    did exactly its job; the failure was on the other side, because the model
    had no grounded way to answer a whole-week question and reconstructed one.

    This tool closes that hole by handing over content the system has ALREADY
    composed and ALREADY validated: `compose.template_brief`, the same
    deterministic prose `/api/runs/{id}/brief` serves and the same text
    `compose.validate_narrative` is tested against. There is no second
    summarisation path here and the model computes nothing -- it quotes.

    Two deliberate choices:

    - `template_brief` is called WITHOUT a connection, so the Task 14
      `outlook:` line is left out. The outlook's projected figures are not
      finding values, so a model quoting one would be (correctly) rejected by
      the validator -- handing it a number it cannot safely repeat is the
      exact trap this tool exists to remove.
    - the brief is audience-scoped, because that is what the existing
      machinery produces. `audience` defaults to TRANSPORT_MANAGER, the
      broadest of the three, and the returned dict names which one was used
      so the answer can say so.

    The tier counts alongside it are counts of the run's OWN findings, over
    every audience, so "how did we do this week" gets the whole-run shape and
    not just one desk's slice. They reach the validator the same way every
    other tool result does, through `_collect_numbers`.
    """
    if audience is None:
        aud = Audience.TRANSPORT_MANAGER
    else:
        try:
            aud = Audience(str(audience).upper())
        except ValueError:
            valid = ", ".join(a.value for a in Audience)
            raise ValueError(f"unknown audience {audience!r}; valid values are {valid}")

    counts = {t.name: 0 for t in Tier}
    for f in run.findings:
        counts[f.tier.name] += 1

    return {
        "runId": run.run_id,
        "windowLabel": run.window.label,
        "windowKind": run.window_kind,
        "audience": aud.value,
        "findingCount": len(run.findings),
        "tierCounts": counts,
        # The already-composed, already-validated brief. Quote from it.
        "brief": template_brief(run, aud),
    }


_DIGEST_MAX_FINDINGS = 8
_DIGEST_MAX_PER_METRIC = 3


def _context_digest(run) -> str:
    """The same top-8 (at most 3 per metric), worst-first shape
    compose._findings_as_text builds for the brief -- primed into the ask
    system prompt so the common question needs no tool call at all. Not
    audience-scoped (ask has no audience): every non-PASS finding in the
    run is eligible, not just one audience's subset."""
    above_pass = [f for f in run.findings if f.tier is not None and f.tier.name != "PASS"]
    counts: dict[str, int] = {}
    capped = []
    for f in above_pass:
        if len(capped) == _DIGEST_MAX_FINDINGS:
            break
        if counts.get(f.metric_id, 0) < _DIGEST_MAX_PER_METRIC:
            capped.append(f)
            counts[f.metric_id] = counts.get(f.metric_id, 0) + 1

    lines = []
    for f in capped:
        metric = registry.by_id(f.metric_id)
        parts = [
            # The metric ID is carried alongside the label so a follow-up
            # list_findings can be filtered without first spending a call on
            # list_metrics to discover the id -- the exact wasted round trip
            # observed in live testing.
            f"metric={metric.label}", f"metric_id={f.metric_id}",
            f"finding_id={f.id}", f"slice={f.slice.label}", f"tier={f.tier.name}",
            f"observed={f.observed:.2f}{metric.unit}",
        ]
        if f.refs:
            top_ref = f.refs[0]
            parts.append(f"{top_ref.label}={top_ref.value:.2f}{metric.unit}")
        parts.append(f"cause={f.cause.value}")
        if f.owns:
            owned = ", ".join(f"{value} {points:.1f}pts" for value, points, _n in f.owns[:2])
            parts.append(f"owns={owned}")
        lines.append(", ".join(parts))
    return "\n".join(lines) if lines else "(no findings above PASS this run)"


def _build_tools(con, run) -> dict:
    return {
        "list_metrics": lambda **_: _list_metrics(),
        "get_metric": lambda metric_id: _get_metric(metric_id),
        "list_findings": lambda metric_id=None, tier=None, limit=20: _list_findings(
            run, metric_id, tier, limit),
        "explain_finding": lambda finding_id: _explain_finding(run, finding_id),
        "decompose_finding": lambda finding_id, dim: _decompose_finding(con, run, finding_id, dim),
        "summarize_run": lambda audience=None: _summarize_run(run, audience),
    }


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_metrics",
        "description": "List every metric this sweep tracks -- id, label, unit, direction, "
                       "and which dimensions it can be sliced by.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "get_metric",
        "description": "Get one metric's definition by id: unit, direction, reference kinds, "
                       "target (if any), and slice dimensions.",
        "parameters": {"type": "object", "properties": {
            "metric_id": {"type": "string", "description": "One of the ids from list_metrics."},
        }, "required": ["metric_id"]},
    }},
    {"type": "function", "function": {
        "name": "list_findings",
        "description": "List findings from this run, worst first, optionally filtered by "
                       "metric id and/or tier (PASS, WATCH, CONCERN, BREACH).",
        "parameters": {"type": "object", "properties": {
            "metric_id": {"type": "string", "description": "Optional: restrict to one metric id."},
            "tier": {"type": "string", "description": "Optional: PASS, WATCH, CONCERN, or BREACH."},
            "limit": {"type": "integer", "description": "Max findings to return (default 20, max 50)."},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "explain_finding",
        "description": "Full detail on one finding by id: observed value, references, cause, "
                       "the deterministic action, confidence, evidence SQL, and its top "
                       "contributors (owns).",
        "parameters": {"type": "object", "properties": {
            "finding_id": {"type": "string"},
        }, "required": ["finding_id"]},
    }},
    {"type": "function", "function": {
        "name": "decompose_finding",
        "description": "Attribute one finding's gap across a dimension -- VENDOR, SITE, "
                       "TENANT, MODE, DIRECTION, SHIFT, or DELAY_REASON -- worst first.",
        "parameters": {"type": "object", "properties": {
            "finding_id": {"type": "string"},
            "dim": {"type": "string",
                   "description": f"One of: {valid_dims()}."},
        }, "required": ["finding_id", "dim"]},
    }},
    {"type": "function", "function": {
        "name": "summarize_run",
        "description": "The settled summary of this run/week: the window label, how many "
                       "findings landed in each tier, and the system's own already-composed "
                       "brief prose. USE THIS for any whole-week question -- \"review this "
                       "week\", \"how did we do\", \"summarise the run\" -- and quote its "
                       "figures rather than working any out yourself.",
        "parameters": {"type": "object", "properties": {
            "audience": {"type": "string",
                        "description": "Optional: TRANSPORT_MANAGER (default), "
                                       "FACILITIES_HEAD, or LINE_MANAGER."},
        }, "required": []},
    }},
]


def _collect_numbers(obj) -> set[float]:
    """Every numeric leaf in a tool result -- Task 9's validator allows a
    figure the model repeats from a tool result, not just from a Finding
    directly (a decompose_finding row's own points_of_gap, say)."""
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _collect_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _collect_numbers(v)
    return out


def _complete_with_retry(model, messages: list[dict]):
    """Exactly one retry on TruncatedResponse, at double the ceiling that
    was hit (capped at ASK_MAX_RETRY_TOKENS) -- same reasoning as
    compose._call_with_retry, a lower cap since this is clicked on stage."""
    try:
        return model.complete_message(messages, tools=TOOL_SCHEMAS, purpose="ask",
                                      max_tokens=ASK_MAX_TOKENS)
    except TruncatedResponse as e:
        retry_ceiling = min((e.max_tokens or ASK_MAX_TOKENS) * 2, ASK_MAX_RETRY_TOKENS)
        logger.warning("tools: ask truncated (prompt_tokens=%s completion_tokens=%s "
                       "ceiling=%s), retrying once at max_tokens=%s", e.prompt_tokens,
                       e.completion_tokens, e.max_tokens, retry_ceiling)
        return model.complete_message(messages, tools=TOOL_SCHEMAS, purpose="ask",
                                      max_tokens=retry_ceiling)


def ask(con, run, question: str, model=None) -> dict:
    """The bounded interrogator: at most MAX_TOOL_CALLS tool calls, then
    answers from what it gathered (or declines). Always returns
    {answer, withheld, reason, trace} -- trace is populated even when the
    answer is withheld, so the verified numbers a tool actually returned
    stay visible even when the prose is rejected."""
    trace: list[dict] = []
    all_numbers: set[float] = set()

    if model is None:
        api_key = os.environ.get("SARVAM_API_KEY", "")
        if not api_key:
            return {"answer": None, "withheld": True,
                    "reason": "no SARVAM_API_KEY configured", "trace": trace}
        model = SarvamClient(api_key=api_key)

    tools_impl = _build_tools(con, run)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(digest=_context_digest(run))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    for _ in range(MAX_TOOL_CALLS):
        try:
            msg = _complete_with_retry(model, messages)
        except TruncatedResponse as e:
            return {"answer": None, "withheld": True,
                    "reason": f"model truncated twice: {e}", "trace": trace}
        except Exception as exc:
            logger.warning("tools: ask model call failed (%s)", type(exc).__name__, exc_info=True)
            return {"answer": None, "withheld": True,
                    "reason": f"model unavailable ({type(exc).__name__})", "trace": trace}

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            answer = (msg.content or "").strip()
            if not answer:
                return {"answer": None, "withheld": True,
                        "reason": "model returned no answer and called no tool", "trace": trace}
            bad = validate_narrative(answer, run, extra_values=all_numbers)
            if bad is not None:
                return {"answer": None, "withheld": True,
                        "reason": f"answer contained a figure no tool returned: {bad}",
                        "trace": trace}
            return {"answer": answer, "withheld": False, "reason": None, "trace": trace}

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}
            try:
                if name not in tools_impl:
                    raise ValueError(f"unknown tool {name!r}; valid tools are "
                                     f"{', '.join(tools_impl)}")
                result = tools_impl[name](**args)
            except Exception as exc:
                result = {"error": str(exc)}
            trace.append({"tool": name, "arguments": args, "result": result})
            all_numbers |= _collect_numbers(result)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    return {"answer": None, "withheld": True,
            "reason": f"tool call budget ({MAX_TOOL_CALLS}) exhausted", "trace": trace}
