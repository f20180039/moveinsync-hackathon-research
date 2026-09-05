"""Turns a ranked SweepRun into words a human forwards.

Two ways to get there: `template_brief` is deterministic prose over the
findings themselves -- no model, no network, always available. `sarvam_brief`
asks the model once for a better-written version of the same facts, then
VALIDATES every figure it wrote against the findings before trusting it. A
narrative that invents or mis-rounds even one number is worse than plain
prose in a leadership brief, so validation failure (or any exception, or a
truncated response) falls back to the template rather than shipping a maybe.

No SQL here, and no `evidence_sql`/`trip_id` ever reaches the model: it sees
metric labels, slice labels, observed values, references and causes -- never
a raw row.
"""
from __future__ import annotations

import logging
import os
import re

from . import registry
from .model import SarvamClient, TruncatedResponse
from .schemas import Audience, Cause, Dimension, Finding, Tier

logger = logging.getLogger("signaldesk")

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DECIMAL = re.compile(r"-?\d+\.\d+")

MAX_FINDINGS_PER_BRIEF = 8


# ---------------------------------------------------------------------------
# Shared formatting -- the template and the validator MUST agree on how a
# number is rendered, or the template's own honest brief would fail its own
# validator.
# ---------------------------------------------------------------------------

def _rendered(value: float, decimals: int) -> str:
    """The one place a number becomes text at a given precision. Both
    `format_value` (below) and `validate_narrative` route through this exact
    function, so a future change to how a figure is rounded or displayed
    cannot desynchronise the template from the validator that checks it."""
    return f"{value:.{decimals}f}"


def format_value(value: float, unit: str) -> str:
    """1 decimal for a percentage, 2 for a rupee figure -- readable either way,
    but the validator's allowed set is built at both precisions (via
    `_rendered`) so this choice never causes a false rejection."""
    return _rendered(value, 1 if unit == "%" else 2)


def validate_narrative(narrative: str, run) -> str | None:
    """Returns the offending figure, or None if every number checks out.

    Every number in the narrative must match a figure in the findings, at the
    SAME precision it was written with. Only DECIMALS are treated as metric
    claims -- bare integers are counts and years, and ISO dates are stripped
    first.

    If validation fails the brief is sent from the deterministic template
    instead. A wrong number in a leadership brief is worse than plain prose.
    """
    values: set[float] = set()
    for f in run.findings:
        for v in (f.observed, f.gap, abs(f.gap), f.confidence, f.confidence * 100):
            values.add(v)
        for ref in f.refs:
            values.add(ref.value)
    for h in run.feed_health.values():
        values.add(h.confidence)
        values.add(h.confidence * 100)

    # The template renders some claims at 1dp (percentages) and some at 2dp
    # (rupees, confidence); a narrative figure is only wrong if it disagrees
    # with the finding at the precision IT was written with, not at some
    # other precision -- otherwise the template's own 1dp renderings would
    # fail their own validator. Both sets are built through `_rendered`, the
    # same function `format_value` uses, rather than a second, independent
    # formatting path.
    allowed_1dp = {_rendered(v, 1) for v in values}
    allowed_2dp = {_rendered(v, 2) for v in values}

    for raw in _DECIMAL.findall(_ISO_DATE.sub("", narrative)):
        decimals = len(raw.split(".", 1)[1])
        v = float(raw)
        ok = _rendered(v, 1) in allowed_1dp if decimals <= 1 else _rendered(v, 2) in allowed_2dp
        if not ok:
            return raw
    return None


# ---------------------------------------------------------------------------
# template_brief -- the shape a transport manager forwards.
# ---------------------------------------------------------------------------

_CAUSE_PHRASE = {
    Cause.TREND_REGRESSION: "below its own 4-week average",
    Cause.PEER_LAGGARD: "behind its peers",
    Cause.BELOW_TARGET: "below target",
    Cause.LOW_CONFIDENCE: "low data confidence — read with care",
    Cause.DATA_GAP: "could not be measured",
    Cause.ON_REFERENCE: "on reference",
}


def _audience_label(audience: Audience) -> str:
    return audience.value.replace("_", " ").title()


def _top_findings_for(run, audience: Audience) -> list[Finding]:
    """Findings arrive already ranked worst-first (verdict.rank); this is the
    ONE cap both the template and the model's prompt share -- PASS is never
    shown, and at most MAX_FINDINGS_PER_BRIEF survive. On the real dataset an
    audience can carry 150+ findings; sending all of them to the model blew
    the token ceiling with zero prose to show for it (measured 2026-09-05,
    see model.DEFAULT_MAX_TOKENS)."""
    relevant = [f for f in run.findings if audience in f.audiences]
    return [f for f in relevant if f.tier is not Tier.PASS][:MAX_FINDINGS_PER_BRIEF]


def _feed_disclosures(run) -> list[str]:
    out = []
    for h in run.feed_health.values():
        if h.must_be_disclosed:
            quarantined = h.rows_rejected + h.unmatched_keys + h.null_critical_fields
            out.append(f"{h.feed} feed confidence {h.confidence:.2f} — "
                      f"{quarantined:,} rows quarantined")
    return out


def _subject(f: Finding) -> str:
    """The name an action sentence hangs a claim on: the vendor when the slice
    IS a vendor, else the slice's own label ("site X", "overall", ...)."""
    if f.slice.dim is Dimension.VENDOR and f.slice.value:
        return f.slice.value
    return f.slice.label


def _action_sentence(top: Finding) -> str:
    if top.metric_id == "vendor_ota" and top.cause is Cause.PEER_LAGGARD:
        return (f"Action: raise on-time performance with {_subject(top)} "
               f"before the next weekly review.")
    if top.metric_id == "no_show_rate":
        return f"Action: review no-show handling for {_subject(top)} with the site lead."
    if top.metric_id == "cost_per_km":
        return f"Action: review billing for {_subject(top)} against contract rates."
    return "Action: review the top finding with the responsible vendor or site lead."


def _finding_line(f: Finding) -> str:
    metric = registry.by_id(f.metric_id)
    observed = format_value(f.observed, metric.unit)
    cause_phrase = _CAUSE_PHRASE[f.cause]
    ref_str = ", ".join(
        f"{ref.label} {format_value(ref.value, metric.unit)}{metric.unit}" for ref in f.refs)
    body = f"{observed}{metric.unit}, {ref_str}" if ref_str else f"{observed}{metric.unit}"
    line = f"[{f.tier.name}] {metric.label} — {f.slice.label}: {body} ({cause_phrase})"
    if f.must_disclose_confidence:
        line += f" confidence {f.confidence:.2f}"
    return line


def template_brief(run, audience: Audience) -> str:
    """Deterministic prose over the ranked findings for `audience`. Findings
    arrive already ranked worst-first (verdict.rank); this only filters,
    caps and formats."""
    label = _audience_label(audience)
    header = f"Signal Desk — {label} brief — {run.window.label}"

    relevant = [f for f in run.findings if audience in f.audiences]
    count = len(relevant)
    context = f"{count} finding{'s' if count != 1 else ''} for {label}."
    disclosures = _feed_disclosures(run)
    if disclosures:
        context += " " + "; ".join(disclosures)

    above_pass = _top_findings_for(run, audience)

    lines = [header, "", context, ""]
    if not above_pass:
        lines.append(f"Nothing above PASS this week for {label}.")
        return "\n".join(lines)

    lines.extend(_finding_line(f) for f in above_pass)
    lines.append("")
    lines.append(_action_sentence(above_pass[0]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sarvam_brief -- one model call (at most two on a truncated first attempt),
# validated, falling back to the template.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are Signal Desk, writing a short weekly operations brief for the "
    "{audience} of an enterprise employee-transport programme. You are given "
    "a short list of findings, each already tiered, ranked and referenced. "
    "Write for this audience: forwardable prose, not a data dump. Cite the "
    "reference point for every claim you make. Mention confidence only for "
    "findings whose confidence is below 0.9. Introduce no figure that is not "
    "present in the findings below -- never invent or recompute a number. "
    "Do not claim that one finding causes another unless the findings "
    "themselves establish it -- describe co-occurring conditions, never "
    "causation across different slices. Do not use citation markers such as "
    "[1]; write plain prose. "
    "End with exactly one sentence naming the action to take."
)

# The one retry compose._call_with_retry allows, at double the ceiling that
# was hit, never past this. See model.SarvamClient.DEFAULT_MAX_TOKENS for why
# a single fixed ceiling cannot be trusted to never truncate.
MAX_RETRY_TOKENS = 32_000


def _findings_as_text(run, audience: Audience) -> str:
    """The same top-8, non-PASS, worst-first subset `template_brief` shows --
    never every finding for the audience (a real-dataset audience can carry
    150+; the model would rather see the same short list a human does)."""
    lines = []
    for f in _top_findings_for(run, audience):
        metric = registry.by_id(f.metric_id)
        parts = [
            f"metric={metric.label}",
            f"slice={f.slice.label}",
            f"observed={format_value(f.observed, metric.unit)}{metric.unit}",
        ]
        for ref in f.refs:
            parts.append(f"{ref.label}={format_value(ref.value, metric.unit)}{metric.unit}")
        parts.append(f"cause={f.cause.value}")
        if f.confidence < 0.9:
            parts.append(f"confidence={f.confidence:.2f}")
        lines.append(f"[{f.tier.name}] " + ", ".join(parts))
    return "\n".join(lines)


def _call_with_retry(model, messages: list[dict], purpose: str = "brief") -> str:
    """Exactly one retry on `TruncatedResponse`, at double the ceiling that
    was hit (capped at MAX_RETRY_TOKENS) -- never more than that. This is not
    the general resilience machinery `model.SarvamClient` explicitly rules
    out (no backoff, no circuit breaker): sarvam-105b's reasoning overhead is
    measured to be unbounded-variable and task-dependent (2,096-15,427
    completion tokens observed across 5 identical real calls at a 16,000
    ceiling -- see model.py), so a single fixed ceiling cannot be trusted to
    never truncate. Doubling once is the cheapest way to turn that variance
    into a delivered brief rather than a template, without pretending a
    ceiling alone solves it. On a second truncation, this re-raises for the
    caller to fall back to the template -- unbounded retrying is exactly the
    machinery that stays out of scope."""
    try:
        return model.complete(messages, purpose=purpose)
    except TruncatedResponse as e:
        retry_ceiling = min((e.max_tokens or SarvamClient.DEFAULT_MAX_TOKENS) * 2,
                            MAX_RETRY_TOKENS)
        logger.warning("compose: model response truncated (prompt_tokens=%s "
                       "completion_tokens=%s ceiling=%s), retrying once at "
                       "max_tokens=%s", e.prompt_tokens, e.completion_tokens,
                       e.max_tokens, retry_ceiling)
        return model.complete(messages, purpose=purpose, max_tokens=retry_ceiling)


def _compose_with_source(run, audience: Audience, model=None) -> tuple[str, str]:
    """The tuple-returning core both `sarvam_brief` and the API route share, so
    the route can report which path fired without duplicating the logic."""
    if model is None:
        api_key = os.environ.get("SARVAM_API_KEY", "")
        if not api_key:
            logger.info("compose: no SARVAM_API_KEY configured, using template (audience=%s)",
                       audience.value)
            return template_brief(run, audience), "template"
        model = SarvamClient(api_key=api_key)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT.format(audience=_audience_label(audience))},
        {"role": "user", "content": f"Findings:\n{_findings_as_text(run, audience)}"},
    ]

    try:
        narrative = _call_with_retry(model, messages, purpose="brief")
    except TruncatedResponse as e:
        logger.warning("compose: model response truncated again after one retry "
                       "(prompt_tokens=%s completion_tokens=%s ceiling=%s), falling "
                       "back to template (audience=%s)", e.prompt_tokens,
                       e.completion_tokens, e.max_tokens, audience.value)
        return template_brief(run, audience), "template"
    except Exception as exc:
        logger.warning("compose: model call failed (%s), falling back to template "
                       "(audience=%s)", type(exc).__name__, audience.value)
        return template_brief(run, audience), "template"

    bad = validate_narrative(narrative, run)
    if bad is not None:
        logger.warning("compose: model narrative rejected (invented figure %r), "
                       "falling back to template (audience=%s)", bad, audience.value)
        return template_brief(run, audience), "template"

    return narrative, "sarvam"


def sarvam_brief(run, audience: Audience, model=None) -> str:
    """One model call on success; at most two if the first truncates (see
    `_call_with_retry`). Validated either way, falling back to
    `template_brief` on a validation failure, a second TruncatedResponse, or
    any other exception."""
    return _compose_with_source(run, audience, model)[0]


def brief_with_source(run, audience: Audience, model=None) -> tuple[str, str]:
    """As `sarvam_brief`, but also reports which path produced the text --
    `"sarvam"` or `"template"` -- for the API route to expose."""
    return _compose_with_source(run, audience, model)
