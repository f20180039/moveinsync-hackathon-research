"""Turns a ranked SweepRun into words a human forwards.

Two ways to get there: `template_brief` is deterministic prose over the
findings themselves -- no model, no network, always available. `sarvam_brief`
asks the model once for a better-written version of the same facts -- twice
if the first attempt truncates (see `_call_with_retry`) -- then VALIDATES
every figure it wrote against the findings before trusting it. A
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

from . import forecast, registry
from .actions import action_for
from .model import SarvamClient, TruncatedResponse
from .schemas import Audience, Cause, Dimension, Finding, Tier

logger = logging.getLogger("signaldesk")

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Fix-wave C1: the old pattern (`-?\d+\.\d+`, decimals only) let a fabricated
# INTEGER slip straight past validation -- "On-time arrival is 78%, against a
# peer median of 91%" contains no decimal point at all, so the old regex
# never even looked at "78" or "91". The `suffix_num` alternative catches a
# bare integer (or decimal) immediately followed by a unit (%, INR, Rs, ₹) --
# exactly the shape a metric claim takes -- while a bare count like
# "8 findings" or "4 weeks" still matches no alternative and stays exempt,
# since it carries no unit and no decimal point.
#
# Opus review (whole-branch, second pass): the above only ever handled a
# SUFFIX unit -- "78%" -- and missed a PREFIX one: "₹1,200", "Rs 1200",
# "Rs. 1200", "INR 86" all went unchecked, and now that cost_per_km is
# active a rupee figure is a live part of the brief. `prefix_num` adds that
# direction. Both alternatives allow comma grouping in the digits
# (`[\d,]*`, stripped before `float()` in the caller) -- the old pattern's
# bare `\d+` stopped at the first comma, so "1,200%" wrongly yielded just
# "200".
_DECIMAL = re.compile(
    r"(?P<suffix_num>-?\d[\d,]*(?:\.\d+)?)(?=\s*%|\s*(?:INR|₹|Rs\.?))"
    r"|(?:%|INR|₹|Rs\.?)\s*(?P<prefix_num>-?\d[\d,]*(?:\.\d+)?)"
    r"|(?P<bare_decimal>-?\d+\.\d+)"
)

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


def _top_contributors(finding: Finding) -> tuple[tuple[str, float, int], ...]:
    """Fix wave 2: finding.owns is now attached server-side, in sweep.py, for
    every tier >= CONCERN finding (capped at the top 25 by rank) -- this is a
    read-through, not a live decompose() call, so the console's Overview
    cards (and this module) no longer trigger a decompose per card/brief.
    Empty for a PASS, or a finding sweep.py did not attach owns to."""
    return finding.owns


def _owns_line(top: Finding) -> str | None:
    """template_brief's "Owns the shortfall:" line, under the top finding
    only -- the Slack/template surface's own pointer to the same decomposition
    the top finding's action line refers to. None when there is nothing to
    show."""
    contributors = _top_contributors(top)
    if not contributors:
        return None
    parts = ", ".join(f"{value} {points:.1f} pts" for value, points, _n in contributors)
    return f"Owns the shortfall: {parts}"


def validate_narrative(narrative: str, run, audience: Audience | None = None,
                       extra_values=None) -> str | None:
    """Returns the offending figure, or None if every number checks out.

    Every number in the narrative must match a figure in the findings, at the
    SAME precision it was written with. Only DECIMALS are treated as metric
    claims -- bare integers are counts and years, and ISO dates are stripped
    first.

    If validation fails the brief is sent from the deterministic template
    instead. A wrong number in a leadership brief is worse than plain prose.

    `audience`: fix wave 2's decomposition adds one more source of allowed
    figures -- the top finding's own owns (the same two contributors the
    prompt is given via `_findings_as_text`'s "owns:" line), so a narrative
    that repeats "two vendors own 5.2 of the 7 points" is not rejected as
    inventing 5.2. Defaults to None, which adds nothing -- every pre-Task-8
    caller keeps its exact prior behaviour.

    `extra_values`: Task 9's interrogator passes every numeric value any
    tool returned this turn (a tool result can carry a figure -- e.g. a
    decompose_finding row's own points_of_gap -- that is real and correct
    but does not live on any Finding directly). Any iterable of numbers;
    defaults to None, which adds nothing.
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
    if run.safety_alert_count > 0:
        values.add(run.safety_alert_count)
        values.add(run.safety_alert_escort_pct)
    if extra_values:
        for v in extra_values:
            values.add(v)

    top = None
    if audience is not None:
        relevant = _top_findings_for(run, audience)
        top = relevant[0] if relevant else None
    elif run.findings:
        top = run.findings[0]
    if top is not None:
        for _value, points, _n in _top_contributors(top):
            values.add(points)
            values.add(abs(points))

    # The template renders some claims at 1dp (percentages) and some at 2dp
    # (rupees, confidence); a narrative figure is only wrong if it disagrees
    # with the finding at the precision IT was written with, not at some
    # other precision -- otherwise the template's own 1dp renderings would
    # fail their own validator. All three sets are built through `_rendered`,
    # the same function `format_value` uses, rather than a second,
    # independent formatting path. 0dp (fix-wave C1) is what an
    # integer-with-a-unit claim ("78%", no decimal point at all) is checked
    # against -- the old validator never looked at a number like that.
    allowed_0dp = {_rendered(v, 0) for v in values}
    allowed_1dp = {_rendered(v, 1) for v in values}
    allowed_2dp = {_rendered(v, 2) for v in values}

    # Task 16: recurrence.weeks/of ("4 of the last 4 weeks") are integer
    # counts, not metric figures, so they only ever need checking at 0dp --
    # added to allowed_0dp alone rather than into `values` (which would also
    # seed allowed_1dp/2dp with "4.0"/"4.00", numbers no finding ever writes).
    for f in run.findings:
        if f.recurrence is not None:
            weeks, of = f.recurrence
            allowed_0dp.add(_rendered(weeks, 0))
            allowed_0dp.add(_rendered(of, 0))

    for m in _DECIMAL.finditer(_ISO_DATE.sub("", narrative)):
        raw = m.group("suffix_num") or m.group("prefix_num") or m.group("bare_decimal")
        clean = raw.replace(",", "")
        v = float(clean)
        if "." not in clean:
            ok = _rendered(v, 0) in allowed_0dp
        else:
            decimals = len(clean.split(".", 1)[1])
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
    # Task 18: a two-sided (demand) finding names the SIDE, because the two
    # sides cost different things -- above the reference the fleet falls short
    # and employees are stranded, below it vehicles were booked nobody rode.
    Cause.DEMAND_SURGE: "demand above its reference — the fleet may fall short",
    Cause.DEMAND_DROP: "demand below its reference — vehicles may be overbooked",
}


def _audience_label(audience: Audience) -> str:
    return audience.value.replace("_", " ").title()


# Controller ruling (marshal diversity): with 23/24 marshal_compliance
# slices in BREACH and hard-target gaps of ~68 points, an unrestricted top-8
# would be eight marshal lines -- a wall, not a brief with a "coherent cost/
# safety/experience story". At most this many findings from any one metric.
MAX_PER_METRIC_IN_BRIEF = 3


def _top_findings_for(run, audience: Audience) -> list[Finding]:
    """Findings arrive already ranked worst-first (verdict.rank); this is the
    ONE cap both the template and the model's prompt share -- PASS is never
    shown, and at most MAX_FINDINGS_PER_BRIEF survive. On the real dataset an
    audience can carry 150+ findings; sending all of them to the model blew
    the token ceiling with zero prose to show for it (measured 2026-09-05,
    see model.DEFAULT_MAX_TOKENS).

    A second cap, MAX_PER_METRIC_IN_BRIEF, keeps one dominant metric (a hard
    target breaching almost everywhere is the obvious case, but any metric
    could do this) from filling the whole brief on its own: at most 3
    findings per metric_id survive, in rank order. This is a HARD ceiling,
    not a quota backfilled from the same metric -- 20 marshal_compliance
    BREACHes plus 3 ota CONCERNs yields 3 marshal + 3 ota (six lines, not
    padded to eight with three more marshal lines just to hit the cap);
    "fill from the rest" only ever means drawing on OTHER metrics that have
    not hit their own cap yet, never re-admitting the metric that is already
    at its ceiling.
    """
    relevant = [f for f in run.findings if audience in f.audiences]
    above_pass = [f for f in relevant if f.tier is not Tier.PASS]

    counts: dict[str, int] = {}
    capped: list[Finding] = []
    for f in above_pass:
        if len(capped) == MAX_FINDINGS_PER_BRIEF:
            break
        if counts.get(f.metric_id, 0) < MAX_PER_METRIC_IN_BRIEF:
            capped.append(f)
            counts[f.metric_id] = counts.get(f.metric_id, 0) + 1
    return capped


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
    # Task 8a: action_for is the deterministic, tested lookup -- prefer it, and
    # only fall back to the older per-metric guesses below when it has nothing
    # (in practice it always does for a non-PASS finding, since _BY_CAUSE
    # covers every accusatory Cause; the fallback stays as a safety net for a
    # future Cause this lookup has not caught up with yet).
    action = action_for(top)
    if action:
        return f"Action: {action}"
    if top.metric_id == "vendor_ota" and top.cause is Cause.PEER_LAGGARD:
        return (f"Action: raise on-time performance with {_subject(top)} "
               f"before the next weekly review.")
    if top.metric_id == "no_show_rate":
        return f"Action: review no-show handling for {_subject(top)} with the site lead."
    if top.metric_id == "cost_per_km":
        return f"Action: review billing for {_subject(top)} against contract rates."
    return "Action: review the top finding with the responsible vendor or site lead."


def _recurring_suffix(f: Finding) -> str:
    """Task 16: " (recurring, {weeks}/{of} weeks)" for a finding whose own
    metric x slice was ALSO CONCERN-or-worse in at least 3 of the last `of`
    (4) weeks -- "" otherwise, including when recurrence was never computed
    (below the tier floor, past the cap)."""
    if f.recurrence is not None and f.recurrence[0] >= 3:
        weeks, of = f.recurrence
        return f" (recurring, {weeks}/{of} weeks)"
    return ""


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
    line += _recurring_suffix(f)
    return line


_SAFETY_LINE_AUDIENCES = frozenset({Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER})


def _safety_context_line(run) -> str | None:
    """Controller ruling (marshal follow-up): the sharpest safety finding in
    the dataset gets its own line in the brief, not just a number buried
    inside marshal_compliance's decomposition. None when the window carried
    no WOMAN_TRAVELLING_ALONE alert at all."""
    if run.safety_alert_count <= 0:
        return None
    return (f"Safety: MoveInSync raised WOMAN_TRAVELLING_ALONE on {run.safety_alert_count} "
           f"trips this window; an escort was present on "
           f"{_rendered(run.safety_alert_escort_pct, 1)}%.")


def _outlook_line(con, run) -> str | None:
    """Task 14: one deterministic `outlook:` sentence for the top finding,
    computed by forecast.py (a stated four-week same-weekday BASELINE, never a
    forecast or a prediction) -- None when no connection was supplied or the
    baseline cannot be built. The model never writes this line."""
    if con is None:
        return None
    try:
        return forecast.outlook_line(con, run)
    except Exception:
        logger.warning("compose: outlook line failed for run %s", run.run_id, exc_info=True)
        return None


def template_brief(run, audience: Audience, con=None) -> str:
    """Deterministic prose over the ranked findings for `audience`. Findings
    arrive already ranked worst-first (verdict.rank); this only filters,
    caps and formats.

    The top finding gets one extra "Owns the shortfall:" line, read straight
    from its own `owns` (sweep.py attaches this server-side for tier >=
    CONCERN); silently omitted when there is nothing to show.
    """
    label = _audience_label(audience)
    header = f"Signal Desk — {label} brief — {run.window.label}"

    relevant = [f for f in run.findings if audience in f.audiences]
    count = len(relevant)
    context = f"{count} finding{'s' if count != 1 else ''} for {label}."
    disclosures = _feed_disclosures(run)
    if disclosures:
        context += " " + "; ".join(disclosures)
    if audience in _SAFETY_LINE_AUDIENCES:
        safety_line = _safety_context_line(run)
        if safety_line:
            context += " " + safety_line

    above_pass = _top_findings_for(run, audience)

    lines = [header, "", context, ""]
    outlook = _outlook_line(con, run)

    if not above_pass:
        lines.append(f"Nothing above PASS this week for {label}.")
        return "\n".join(lines)

    for i, f in enumerate(above_pass):
        lines.append(_finding_line(f))
        action = action_for(f)
        if action:
            lines.append(f"  → {action}")
        if i == 0:
            owns = _owns_line(f)
            if owns:
                lines.append(f"  {owns}")
    lines.append("")
    if outlook:
        lines.append(outlook)
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
    "End with exactly one sentence naming the action to take. Each finding "
    "carries an action. Reproduce its meaning in your closing sentence. Do "
    "not invent an action that is not there."
)

# The one retry compose._call_with_retry allows, at double the ceiling that
# was hit, never past this. See model.SarvamClient.DEFAULT_MAX_TOKENS for why
# a single fixed ceiling cannot be trusted to never truncate.
MAX_RETRY_TOKENS = 32_000


def _findings_as_text(run, audience: Audience) -> str:
    """The same top-8, non-PASS, worst-first subset `template_brief` shows --
    never every finding for the audience (a real-dataset audience can carry
    150+; the model would rather see the same short list a human does).

    The top finding's "owns:" line is read straight from its own `owns`
    (sweep.py attaches this server-side); omitted when there is nothing to
    show, including for a finding sweep.py did not attach owns to.
    """
    lines = []
    top_findings = _top_findings_for(run, audience)
    for i, f in enumerate(top_findings):
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
        action = action_for(f)
        if action:
            lines.append(f"  action: {action}")
        # Task 16: only surfaced to the model at the same >=3-of-4 threshold
        # that flags the action prefix and the template's own brief suffix --
        # a finding recurrence was computed for but that ISN'T recurring
        # (weeks 0-2) stays silent here rather than reading as a callout.
        if f.recurrence is not None and f.recurrence[0] >= 3:
            weeks, of = f.recurrence
            lines.append(f"  recurring: {weeks}/{of}")
        if i == 0:
            contributors = _top_contributors(f)
            if contributors:
                owned = ", ".join(
                    f"{value} {points:.1f}pts" for value, points, _n in contributors)
                lines.append(f"  owns: {owned} of {abs(f.gap):.1f} points")
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


def _compose_with_source(run, audience: Audience, model=None, con=None) -> tuple[str, str]:
    """The tuple-returning core both `sarvam_brief` and the API route share, so
    the route can report which path fired without duplicating the logic."""
    if model is None:
        api_key = os.environ.get("SARVAM_API_KEY", "")
        if not api_key:
            logger.info("compose: no SARVAM_API_KEY configured, using template (audience=%s)",
                       audience.value)
            return template_brief(run, audience, con), "template"
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
        return template_brief(run, audience, con), "template"
    except Exception as exc:
        logger.warning("compose: model call failed (%s), falling back to template "
                       "(audience=%s)", type(exc).__name__, audience.value)
        return template_brief(run, audience, con), "template"

    bad = validate_narrative(narrative, run, audience=audience)
    if bad is not None:
        logger.warning("compose: model narrative rejected (invented figure %r), "
                       "falling back to template (audience=%s)", bad, audience.value)
        return template_brief(run, audience, con), "template"

    # Task 14: the outlook line is appended AFTER validation and is written
    # by forecast.py, not by the model -- so a stated baseline can never be
    # reworded into a prediction, and validate_narrative never sees a figure
    # it has no finding for.
    outlook = _outlook_line(con, run)
    if outlook:
        narrative = f"{narrative}\n\n{outlook}"
    return narrative, "sarvam"


def sarvam_brief(run, audience: Audience, model=None, con=None) -> str:
    """One model call on success; at most two if the first truncates (see
    `_call_with_retry`). Validated either way, falling back to
    `template_brief` on a validation failure, a second TruncatedResponse, or
    any other exception."""
    return _compose_with_source(run, audience, model, con)[0]


def brief_with_source(run, audience: Audience, model=None, con=None) -> tuple[str, str]:
    """As `sarvam_brief`, but also reports which path produced the text --
    `"sarvam"` or `"template"` -- for the API route to expose."""
    return _compose_with_source(run, audience, model, con)
