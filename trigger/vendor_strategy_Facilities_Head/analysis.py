"""The LangChain layer for all three levels.

WHAT LANGCHAIN IS DOING, precisely: `ChatPromptTemplate | ChatOpenAI |
PydanticOutputParser`. The prompt carries ONLY computed facts; the parser
forces the answer into the schema so the Slack report never depends on the
model's formatting. Nothing agentic, no tools, no retrieval -- the model has
no way to reach data it was not handed, which is exactly the property that
stops it inventing a contract term or an SLA that does not exist.

WHAT THE MODEL IS FOR: interpretation, synthesis across metrics, strategic
implication, narrative. Not arithmetic -- `metrics.py` and `scorecard.py`
own every number, and the guards below re-assert the deterministic
recommendation floor, the confidence level and the vendor name after parsing.

WHAT THE MODEL IS FORBIDDEN: any figure not in its context, any contract
term, SLA target, penalty, complaint or capacity claim (none of which exist
in the dataset), and any verdict outside the fixed vocabulary.
"""
from __future__ import annotations

import json
import logging

from ..common import llm as llm_mod
from . import scorecard as sc
from .schema import (DailyBrief, MonthlyReview, QuarterExecutive, VendorNote,
                     VendorStrategy)

logger = logging.getLogger("trigger")

_GROUND_RULES = (
    "Rules you must not break:\n"
    "- Every number you write must already appear in the CONTEXT. Never "
    "compute, estimate, extrapolate or round a new figure.\n"
    "- The dataset contains NO contracted SLA targets, contract terms, "
    "penalty clauses, complaint tickets, vendor fleet sizes or quoted rates. "
    "Never refer to any of these as if you had them.\n"
    "- Where cost data is missing or thin, say value-for-money cannot be "
    "concluded on price. Do not guess at it.\n"
    "- Judge value for money, not price. High cost with strong, consistent "
    "service can be good value; low cost with poor service is not.\n"
    "- Write for a Facilities Head deciding what to do, not for an analyst "
    "reading a table. Decisions over data.\n"
    "- No preamble, no markdown fences, no text outside the JSON."
)

_DAILY_SYSTEM = (
    "You are the vendor performance analyst for an enterprise employee-"
    "transport programme, writing the Facilities Head's end-of-day note.\n"
    + _GROUND_RULES +
    "\n- One day is one day: flag what stands out today against today's own "
    "peers, and do not claim a trend from a single day."
)

_MONTHLY_SYSTEM = (
    "You are the vendor performance analyst for an enterprise employee-"
    "transport programme, writing the Facilities Head's month-end review.\n"
    + _GROUND_RULES +
    "\n- You are given each vendor's scorecard and its within-month trend. "
    "Say whether this month's problems look systemic across vendors or "
    "isolated to a few."
)

_QUARTER_VENDOR_SYSTEM = (
    "You are the vendor strategy analyst for an enterprise employee-transport "
    "programme. You are given ONE vendor's full quarter and must produce the "
    "Facilities Head's strategic verdict on it.\n"
    + _GROUND_RULES +
    "\n- `recommendation_floor` is what the deterministic model concluded. "
    "Use it unless the evidence clearly warrants ONE notch of movement, and "
    "if you move it, say why in the evidence.\n"
    "- `confidence` is given to you and is derived from evidence volume. "
    "Never state a confidence higher than the one given.\n"
    "- A quarterly AVERAGE hides a trajectory. If the monthly series moves "
    "consistently one way, that direction is the finding, not the average."
)

_QUARTER_EXEC_SYSTEM = (
    "You are the vendor strategy analyst writing the executive summary of a "
    "quarterly vendor review for a Facilities Head.\n"
    + _GROUND_RULES +
    "\n- You are given every vendor's already-decided verdict. Do not "
    "re-litigate them; synthesise the programme-level picture and the "
    "strategy for next quarter.\n"
    "- Name concentration risk if a small number of vendors carry most of "
    "the volume, and say so with the share given to you."
)

_HUMAN = "CONTEXT:\n{context}\n\nReturn ONLY JSON matching this schema:\n{format_instructions}\n"


# ---------------------------------------------------------------------------
# context builders -- aggregates only, never a trip row or a trip_id
# ---------------------------------------------------------------------------

_VENDOR_KEYS = ("vendor", "trips", "onTimePct", "slaAdherencePct", "completionPct",
                "avgDelayMin", "p90DelayMin", "delayedTripPct",
                "driverAttributedDelays", "driverNonCompliance", "noShowPct",
                "cancelledBookings", "alerts", "alertsPer100Trips", "severeAlerts",
                "routeRating", "driverRating", "safetyRating", "ratingResponses",
                "totalCost", "costPerTrip", "costPerOnTimeTrip", "costPerKm",
                "costCoveragePct", "avgOccupancy", "poorDays", "ratedDays",
                "onTimeVolatility")


def _slim(v: dict) -> dict:
    out = {k: v[k] for k in _VENDOR_KEYS if v.get(k) is not None}
    if "scores" in v:
        out["scores"] = v["scores"]
    if v.get("scoreCaveats"):
        out["scoreCaveats"] = v["scoreCaveats"]
    if v.get("quadrant"):
        out["valuePosition"] = v["quadrant"]
    if v.get("trend"):
        out["trend"] = v["trend"]
    return out


def daily_context(window, board, totals) -> str:
    return json.dumps({
        "day": window.label,
        "note": window.note,
        "programme_totals": totals,
        "vendors": [_slim(v) for v in board["ranked"]],
        "vendors_below_ranking_floor": [_slim(v) for v in board["unranked"]],
        "peer_medians": board["peers"],
        "definitions": {
            "onTimePct": "delay_minutes <= 5 (MoveInSync's own column)",
            "slaAdherencePct": "delay_minutes <= 15",
            "costPerOnTimeTrip": "vendor spend divided by on-time trips",
        },
    }, indent=1)


def monthly_context(window, board, totals) -> str:
    return json.dumps({
        "month": window.label,
        "note": window.note,
        "trend_parts": "the month split into first / middle / final third",
        "programme_totals": totals,
        "vendors": [_slim(v) for v in board["ranked"]],
        "vendors_below_ranking_floor": [_slim(v) for v in board["unranked"]],
        "peer_medians": board["peers"],
        "scoring_model": SCORING_NOTE,
    }, indent=1)


def quarter_vendor_context(window, v: dict, board, totals) -> str:
    return json.dumps({
        "quarter": window.label,
        "note": window.note,
        "months_in_quarter": list(window.sub_labels),
        "vendor": _slim(v),
        "rank": v.get("rank"),
        "of_ranked_vendors": len(board["ranked"]),
        "recommendation_floor": v["recommendationFloor"],
        "confidence": v["confidence"],
        "confidence_reason": v["confidenceReason"],
        "deterministic_evidence": v["evidence"],
        "peer_medians": board["peers"],
        "programme_totals": totals,
        "allowed_recommendations": list(sc.RECOMMENDATIONS),
        "scoring_model": SCORING_NOTE,
    }, indent=1)


def quarter_exec_context(window, board, totals, verdicts) -> str:
    top = board["ranked"][:3]
    share = None
    if totals["trips"]:
        share = round(100.0 * sum(v["trips"] for v in top) / totals["trips"], 1)
    return json.dumps({
        "quarter": window.label,
        "note": window.note,
        "months_in_quarter": list(window.sub_labels),
        "programme_totals": totals,
        "top3_volume_share_pct": share,
        "vendor_verdicts": [{
            "vendor": x.vendor, "recommendation": x.recommendation,
            "confidence": x.confidence, "trend": x.performance_trend,
            "value_for_money": x.value_for_money,
            "concerns": x.key_concerns[:2], "strengths": x.key_strengths[:2],
        } for x in verdicts],
        "scores": [{"vendor": v["vendor"], "overall": v["scores"]["overall"],
                    "service": v["scores"]["service"],
                    "reliability": v["scores"]["reliability"],
                    "costValue": v["scores"]["costValue"],
                    "trips": v["trips"], "valuePosition": v["quadrant"],
                    "onTimeTrend": v["trend"]["onTimeTrend"],
                    "onTimeChangePP": v["trend"]["onTimeChangePP"],
                    "costChangePct": v["trend"]["costChangePct"]}
                   for v in board["ranked"]],
    }, indent=1)


SCORING_NOTE = (
    "overall = 0.40 service + 0.30 reliability + 0.30 cost value. "
    "service = 0.45 on-time + 0.30 SLA adherence + 0.15 completion + 0.10 rider "
    "rating (renormalised when unrated). reliability = 0.50 consistency "
    "(100 - 2x stdev of daily on-time) + 0.30 good-day share + 0.20 operational "
    "cleanliness. cost value is PEER-RELATIVE around the median cost per "
    "on-time trip: 50 at the median, 100 at half of it, 0 at twice it -- so an "
    "average vendor scores 50 there by construction and overall scores sit "
    "below service scores. It ranks vendors against each other, it is not an "
    "absolute grade."
)


# ---------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------

def _invoke(system: str, contexts: list[str], model_cls, cfg, llm=None):
    """One chain, N independent invocations. Returns (results, source) where a
    result is a parsed model or None -- the caller supplies the fallback."""
    model = llm_mod.build_llm(cfg, llm)
    if model is None:
        return [None] * len(contexts), "fallback"

    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    parser = PydanticOutputParser(pydantic_object=model_cls)
    prompt = ChatPromptTemplate.from_messages(
        [("system", system), ("human", _HUMAN)]
    ).partial(format_instructions=parser.get_format_instructions())
    chain = prompt | model

    try:
        messages = chain.batch([{"context": c} for c in contexts],
                               config={"max_concurrency": 4}, return_exceptions=True)
    except Exception as exc:
        logger.warning("analysis: batch failed (%s)", type(exc).__name__)
        return [None] * len(contexts), "fallback"

    out, ok = [], 0
    for message in messages:
        if isinstance(message, Exception):
            logger.warning("analysis: call failed (%s)", type(message).__name__)
            out.append(None)
            continue
        text = llm_mod.message_text(message)
        parsed = None
        try:
            parsed = parser.parse(text)
        except Exception:
            raw = llm_mod.lenient_json(text)
            if raw is not None:
                try:
                    parsed = model_cls.model_validate(raw)
                except Exception as exc:
                    logger.warning("analysis: JSON did not validate (%s)",
                                   type(exc).__name__)
        if parsed is None:
            logger.warning("analysis: output unparseable, falling back")
        else:
            ok += 1
        out.append(parsed)

    source = "langchain" if ok == len(contexts) else ("fallback" if ok == 0 else "mixed")
    return out, source
