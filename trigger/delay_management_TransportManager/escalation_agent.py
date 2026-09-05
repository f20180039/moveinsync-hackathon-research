"""The LangChain reasoning layer -- one independent call per problematic ride.

WHAT IS DETERMINISTIC AND WHAT IS THE MODEL'S, precisely:

  delay_analyzer.py (Python)   every minute figure, which thresholds were
                               crossed, how many factors a ride has, the
                               severity FLOOR, the data-quality notes
  this file (the model)        what actually happened, the likely cause when
                               several factors are present, the severity
                               within/above the floor, whether the Team
                               Manager must act, and the recommended action

The model is told, in the system prompt, that every number is already given
and it must not compute one. `delay_minutes` is overwritten with the
deterministic value after parsing, so a model slip cannot put a wrong number
in front of a manager.

MULTIPLE RIDES: each ride is its OWN chain invocation, sent through
`chain.batch(...)` with bounded concurrency -- so four problematic rides get
four independent pieces of reasoning, not one blended paragraph. A ride whose
call or parse fails degrades to a deterministic escalation; the other rides
are unaffected.
"""
from __future__ import annotations

import json
import logging

from ..common import llm as llm_mod
from .delay_analyzer import _ORDER
from .schema import SEVERITIES, Escalation

logger = logging.getLogger("trigger")

_SYSTEM = (
    "You are the escalation assistant for an enterprise employee-transport "
    "operations desk. You are given ONE ride that automated checks have "
    "flagged, with every relevant fact already computed.\n"
    "Rules you must not break:\n"
    "- Every number you write must already appear in the facts. Never "
    "compute, estimate or infer a new figure. The arithmetic is already done.\n"
    "- Reason about THIS ride only. Do not generalise across the fleet.\n"
    "- When several factors are present, say which one is most likely the "
    "primary cause and why, rather than listing them flatly.\n"
    "- severity_floor is what the deterministic checks already established. "
    "You may raise the severity if the combination warrants it; do not go "
    "below the floor.\n"
    "- The recommended action must be something a Team Manager can do in the "
    "next few minutes: call someone, reassign something, check something.\n"
    "- Where a fact is missing or marked unreliable, say so rather than "
    "assuming it.\n"
    "- No preamble, no markdown fences, no text outside the JSON."
)

_HUMAN = (
    "Ride {ride_id} was flagged. Facts:\n{facts}\n\n"
    "Return ONLY JSON matching this schema:\n{format_instructions}\n"
)


def _facts(analysis: dict) -> str:
    """What the model sees: the deterministic picture, nothing else. No raw
    rows, no employee ids -- the same discipline `signaldesk.compose` keeps."""
    ride = analysis["ride"]
    keep = ("rideId", "status", "etaBasis", "nowLocal", "vendor", "site",
            "direction", "shiftBand", "routeSource",
            "scheduledStartLocal", "actualStartLocal", "plannedArrivalLocal",
            "expectedArrivalLocal", "actualArrivalLocal",
            "driverStartSlipMin", "etaDeviationMin", "plannedDurationMin",
            "elapsedMin", "minutesToStart", "overdueMin",
            "moveInSyncDelayMin", "delayReason",
            "driverNonCompliance", "cabNonCompliance",
            "plannedRiders", "actualRiders", "noShowRiders", "cabCapacity",
            "legs", "adhocLegs", "guestLegs", "cancelledLegs", "noShowLegs",
            "notBoardedLegs", "maxPickupSlipMin",
            "alertCount", "alertTypes", "worstAlertSeverity", "escortPresent")
    return json.dumps({
        "ride": {k: ride.get(k) for k in keep if ride.get(k) is not None},
        "detected_factors": [
            {"code": f["code"], "what": f["label"], "minutes": f["minutes"],
             "detail": f["detail"]} for f in analysis["factors"]],
        "computed_delay_minutes": analysis["delayMinutes"],
        "severity_floor": analysis["severityHint"],
        "attention_floor": analysis["attentionHint"],
        "data_quality_notes": analysis["dataIssues"],
        "note": ("etaBasis 'projected' means the ride is still running and the "
                 "arrival is inferred from the driver's actual start plus the "
                 "planned duration -- it is not a reported live ETA. "
                 "'observed' means the ride has finished. The dataset has no "
                 "booking timestamp; Adhoc sign-ins are the only late-booking "
                 "signal available."),
    }, indent=1)


def fallback_escalation(analysis: dict, reason: str) -> Escalation:
    """Deterministic escalation -- no model, no network. Same structure, so
    Slack renders it identically and a model outage costs prose, not the
    notification."""
    factors = analysis["factors"]
    codes = analysis["factorCodes"]
    primary = factors[0] if factors else None
    issue = ("Multiple contributing factors" if len(factors) >= 2
             else (primary["label"] if primary else "Operational exception"))
    cause = (f"{primary['label'].lower()} — {primary['detail']}" if primary
             else "no single dominant factor")
    action = _default_action(codes)
    return Escalation(
        ride_id=str(analysis["rideId"]),
        issue_type=issue,
        severity=analysis["severityHint"],
        requires_attention=analysis["attentionHint"],
        delay_minutes=analysis["delayMinutes"],
        likely_cause=cause,
        reasoning=("Deterministic checks only (" + reason + "). Factors: "
                   + "; ".join(f["detail"] for f in factors[:3]) + "."),
        recommended_action=action,
    )


def _default_action(codes: list[str]) -> str:
    if "SAFETY_ALERT" in codes:
        return "Check the open alert on this ride and confirm the rider is safe."
    if "ETA_DEVIATION" in codes or "OVERDUE" in codes:
        return ("Call the driver, confirm whether the arrival time can be held, "
                "and warn the site if it cannot.")
    if "DRIVER_LATE_START" in codes or "DRIVER_CAUSE" in codes:
        return "Contact the vendor about this driver's start time on this ride."
    if "LATE_BOOKING" in codes or "BOOKING_CANCELLED" in codes:
        return "Confirm the roster for this trip with the booking desk."
    if "NO_SHOW_IMPACT" in codes:
        return "Confirm with the site whether these riders still need transport."
    return "Review this ride with the site lead."


def _clean(esc: Escalation, analysis: dict) -> Escalation:
    """Trust the model's words, not its arithmetic or its floor."""
    severity = esc.severity.strip().upper()
    if severity not in SEVERITIES:
        severity = analysis["severityHint"]
    floor = analysis["severityHint"]
    if _ORDER[severity] < _ORDER[floor]:
        logger.info("trigger: ride %s — model said %s, floor is %s; keeping the floor",
                    analysis["rideId"], severity, floor)
        severity = floor
    return esc.model_copy(update={
        "ride_id": str(analysis["rideId"]),
        "severity": severity,
        # Never let a model-written number reach a manager: the figure is
        # whatever delay_analyzer computed.
        "delay_minutes": analysis["delayMinutes"],
    })


def reason(analyses: list[dict], cfg, llm=None) -> tuple[list[Escalation], str]:
    """One independent chain call per ride. Returns the escalations and which
    path produced them -- "langchain", "fallback", or "mixed"."""
    if not analyses:
        return [], "none"

    model = llm_mod.build_llm(cfg, llm)
    if model is None:
        logger.info("trigger: SARVAM_API_KEY not set, using deterministic escalations")
        return [fallback_escalation(a, "no SARVAM_API_KEY configured")
                for a in analyses], "fallback"

    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    parser = PydanticOutputParser(pydantic_object=Escalation)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM), ("human", _HUMAN)]
    ).partial(format_instructions=parser.get_format_instructions())
    chain = prompt | model

    inputs = [{"ride_id": a["rideId"], "facts": _facts(a)} for a in analyses]
    try:
        # One call per ride, run concurrently. return_exceptions keeps one
        # bad ride from taking the batch down with it.
        messages = chain.batch(inputs, config={"max_concurrency": 4},
                               return_exceptions=True)
    except Exception as exc:
        logger.warning("trigger: batch call failed (%s), using deterministic escalations",
                       type(exc).__name__)
        return [fallback_escalation(a, f"model call failed ({type(exc).__name__})")
                for a in analyses], "fallback"

    out, sources = [], []
    for analysis, message in zip(analyses, messages):
        if isinstance(message, Exception):
            logger.warning("trigger: ride %s model call failed (%s)",
                           analysis["rideId"], type(message).__name__)
            out.append(fallback_escalation(analysis,
                                           f"model call failed ({type(message).__name__})"))
            sources.append("fallback")
            continue
        text = llm_mod.message_text(message)
        esc = None
        try:
            esc = parser.parse(text)
        except Exception:
            raw = llm_mod.lenient_json(text)
            if raw is not None:
                try:
                    esc = Escalation.model_validate(raw)
                except Exception as exc:
                    logger.warning("trigger: ride %s JSON did not validate (%s)",
                                   analysis["rideId"], type(exc).__name__)
        if esc is None:
            logger.warning("trigger: ride %s output unparseable, falling back",
                           analysis["rideId"])
            out.append(fallback_escalation(analysis, "model output was not valid JSON"))
            sources.append("fallback")
        else:
            out.append(_clean(esc, analysis))
            sources.append("langchain")

    unique = set(sources)
    source = unique.pop() if len(unique) == 1 else "mixed"
    return out, source
