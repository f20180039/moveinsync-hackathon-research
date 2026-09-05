"""The LangChain step: statistics in, a structured shift plan out.

One chain, one call: `ChatPromptTemplate | ChatOpenAI | PydanticOutputParser`.
The model is Sarvam, reached through its OpenAI-compatible endpoint -- the
same BASE_URL and MODEL the existing `signaldesk.model` layer uses, imported
rather than restated, so a model change there carries here.

Two rules borrowed from `signaldesk.compose`, and they are the reason this is
safe to send a manager:
  1. The model never computes a number. Every figure it may use is handed to
     it, already computed, in the context block.
  2. If the model is unavailable, unparseable or unconfigured, the job still
     ships a plan -- `fallback_plan` builds the same structure straight from
     the forecast. A deterministic plan beats a missing one at 06:30.
"""
from __future__ import annotations

import json
import logging
import os
import re

from ..common import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from .schema import ShiftBlock, ShiftPlan
from signaldesk import model as _model

logger = logging.getLogger("trigger")

_BAND_WINDOWS = {           # signaldesk.ingest buckets shift_type into these
    "EARLY": "04:00-08:00",
    "DAY": "08:00-16:00",
    "EVENING": "16:00-22:00",
    "NIGHT": "22:00-04:00",
    "UNKNOWN": "all day",
}

_SYSTEM = (
    "You are the transport planning assistant for an enterprise employee "
    "transport programme. You write the Transport Manager's shift plan for "
    "ONE day, before the first shift runs.\n"
    "Rules you must not break:\n"
    "- Every number you write must already appear in the CONTEXT. Never "
    "compute, estimate, extrapolate or round a new figure.\n"
    "- The forecast has already been produced. Explain and allocate it; do "
    "not second-guess it with arithmetic of your own.\n"
    "- Be concrete and operational. A shift block a dispatcher can act on "
    "beats a paragraph of analysis.\n"
    "- Where the data cannot support a claim, say so plainly instead of "
    "filling the gap.\n"
    "- No preamble, no markdown fences, no commentary outside the JSON."
)

_HUMAN = (
    "Plan the transport for {target_date} ({weekday}).\n\n"
    "CONTEXT (every figure you may use):\n{context}\n\n"
    "Return ONLY JSON matching this schema:\n{format_instructions}\n"
)


def _compact(stats: dict) -> dict:
    """The model sees aggregates only -- never a trip row, never a trip_id.

    Same discipline as `signaldesk.compose._findings_as_text`: this keeps the
    prompt small (one call, flat cost as the dataset grows) and keeps
    personal and operational row data out of the model entirely.
    """
    f = stats["forecast"]
    r = stats["reliability"]
    w = stats["window"]
    return {
        "targetDate": w["targetDate"],
        "weekday": w["targetWeekday"],
        "historyWindowDays": w["historyDays"],
        "dataThrough": w["dataLatestDate"],
        "forecast": {
            "trips": f["forecastTrips"],
            "employees": f["forecastEmployees"],
            "vehiclesRequired": f["vehiclesRequired"],
            "vehiclesWithBuffer": f["vehiclesWithBuffer"],
            "driversRequired": f["driversRequired"],
            "bufferPct": f["bufferPct"],
            "basis": f["basis"],
            "profileBasis": f["profileBasis"],
            "trendFactor": f["trendFactor"],
            "employeesPerTrip": f["employeesPerTrip"],
        },
        "peakHours": f["peakHours"],
        "shiftBlocks": f["byBand"],
        "recentDays": stats["daily"][-7:],
        "sameWeekdayHistory": stats["sameWeekdayHistory"],
        "reliability": r,
        "vendors": stats["vendors"],
        "sites": stats["sites"],
        "alertsPerDay": stats["alerts"].get("perDay", []),
        "boarding": stats["boarding"],
        "feedback": stats["feedback"],
        "feedConfidence": {k: v["confidence"] for k, v in stats["feedHealth"].items()},
    }


def _lenient_json(text: str) -> dict | None:
    """Sarvam sometimes wraps JSON in a fence or trails a sentence after it.
    Take the outermost JSON object and try that before giving up."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def fallback_plan(stats: dict, reason: str) -> ShiftPlan:
    """The deterministic plan. No model, no network -- built straight from
    the forecast, in the same shape the model is asked for, so the Slack
    message is identical in structure either way."""
    f = stats["forecast"]
    r = stats["reliability"]
    w = stats["window"]

    blocks = [
        ShiftBlock(
            window=_BAND_WINDOWS.get(b["band"], "all day"),
            band=b["band"], direction=b["direction"],
            vehicles=b["vehiclesWithBuffer"],
            drivers=b["vehiclesWithBuffer"],
            expected_trips=b["forecastTrips"],
            expected_employees=b["forecastEmployees"],
            note=(f"historical on-time {b['historicalOnTimePct']}%, "
                  f"occupancy {b['avgOccupancy']}"),
        )
        for b in f["byBand"]
    ]

    risks = []
    if r.get("noShowPct") is not None and r["noShowPct"] >= 5:
        risks.append(f"No-shows are running at {r['noShowPct']}% of planned "
                     f"headcount — seats booked that do not travel.")
    occ = r.get("avgOccupancy")
    if occ is not None and occ < 0.7:
        risks.append(f"Average cab occupancy is {occ} — routes are running "
                     f"below capacity.")
    weak = [b for b in f["byBand"]
            if b["historicalOnTimePct"] is not None and b["historicalOnTimePct"] < 90]
    for b in weak[:2]:
        risks.append(f"{b['band']} {b['direction']} has historical on-time "
                     f"{b['historicalOnTimePct']}% — the weakest block of the day.")

    anomalies = []
    for a in stats["alerts"].get("perDay", [])[:3]:
        anomalies.append(f"{a['eventType']} ({a['severity']}) averages "
                         f"{a['perDay']}/day in this window.")
    low = [k for k, v in stats["feedHealth"].items() if v["confidence"] < 0.9]
    if low:
        anomalies.append(f"Feed confidence below 0.9: {', '.join(low)} — "
                         f"read the figures with that in mind.")

    actions = [
        f"Roster {f['vehiclesWithBuffer']} vehicles and "
        f"{f['driversRequired']} drivers, including the "
        f"{f['bufferPct']}% standby buffer.",
    ]
    if f["peakHours"]:
        p = f["peakHours"][0]
        actions.append(f"Hold standby capacity for the {p['window']} peak "
                       f"({p['shareOfDayPct']}% of the day's trips).")
    slow = [v for v in stats["vendors"]
            if v["onTimePct"] is not None and v["onTimePct"] < 90][:1]
    if slow:
        actions.append(f"Confirm cab release times with {slow[0]['vendor']} "
                       f"(on-time {slow[0]['onTimePct']}%).")

    return ShiftPlan(
        headline=(f"{w['targetDate']} ({w['targetWeekday']}): "
                  f"{f['forecastTrips']} trips forecast, "
                  f"{f['vehiclesWithBuffer']} vehicles to roster."),
        expected_demand=(f"{f['forecastTrips']} trips and about "
                         f"{f['forecastEmployees']} employees, from the "
                         f"{f['basis']}, trend factor {f['trendFactor']}."),
        peak_periods=[f"{p['window']} — {p['shareOfDayPct']}% of the day's trips, "
                      f"historical on-time {p['historicalOnTimePct']}%"
                      for p in f["peakHours"]],
        shift_blocks=blocks,
        capacity_risks=risks,
        anomalies=anomalies,
        eta_considerations=[
            f"Historical on-time is {r['onTimePct']}% at {r['onTimeDefinition']}; "
            f"average delay {r['avgDelayMin']} min, p90 {r['p90DelayMin']} min.",
        ] + ([f"Top delay reason in window: {r['topDelayReasons'][0]['reason']} "
              f"({r['topDelayReasons'][0]['trips']} trips)."]
             if r.get("topDelayReasons") else []),
        recommended_actions=actions,
        reasoning=f"Deterministic plan — {reason}.",
    )


def build_chain(cfg, llm=None):
    """The LangChain pipeline, or None when there is no key to call with.

    `llm` injects a chat model instead of constructing the Sarvam one -- the
    same `model=None` seam `signaldesk.compose` uses, so the chain can be
    exercised (see `selftest.py`) without a network call.
    """
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if llm is None and not api_key:
        return None, None

    # Task 19: langchain is an OPTIONAL dependency (trigger/requirements.txt,
    # not service/requirements.txt), so a service-venv run must degrade to the
    # deterministic plan rather than dying on an import. "The model is
    # unavailable" and "the model package is not installed" are the same
    # situation to a Transport Manager at 06:30.
    try:
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        logger.info("trigger: langchain not installed (%s), using deterministic plan", exc.name)
        return None, None

    parser = PydanticOutputParser(pydantic_object=ShiftPlan)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM), ("human", _HUMAN)]
    ).partial(format_instructions=parser.get_format_instructions())

    llm = llm or ChatOpenAI(
        model=cfg.model,
        base_url=cfg.base_url,           # Sarvam, OpenAI-compatible
        api_key=api_key,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=120,
        max_retries=1,
    )
    return prompt | llm, parser


def plan(stats: dict, cfg, llm=None) -> tuple[ShiftPlan, str]:
    """Returns the plan and which path produced it -- "langchain" or
    "fallback" -- so the Slack footer can say so honestly."""
    chain, parser = build_chain(cfg, llm)
    if chain is None:
        logger.info("trigger: SARVAM_API_KEY not set, using deterministic plan")
        return fallback_plan(stats, "no SARVAM_API_KEY configured"), "fallback"

    context = json.dumps(_compact(stats), indent=1)
    w = stats["window"]
    try:
        message = chain.invoke({
            "target_date": w["targetDate"],
            "weekday": w["targetWeekday"],
            "context": context,
        })
        text = message.content if hasattr(message, "content") else str(message)
        if isinstance(text, list):     # some providers return content parts
            text = "".join(part.get("text", "") for part in text
                           if isinstance(part, dict))
    except Exception as exc:
        logger.warning("trigger: model call failed (%s), using deterministic plan",
                       type(exc).__name__)
        return fallback_plan(stats, f"model call failed ({type(exc).__name__})"), "fallback"

    try:
        return parser.parse(text), "langchain"
    except Exception:
        raw = _lenient_json(text)
        if raw is not None:
            try:
                return ShiftPlan.model_validate(raw), "langchain"
            except Exception as exc:
                logger.warning("trigger: model JSON did not validate (%s)",
                               type(exc).__name__)
        logger.warning("trigger: model output unparseable, using deterministic plan")
        return fallback_plan(stats, "model output was not valid plan JSON"), "fallback"
