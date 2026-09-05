"""The model layer for the fleet plan -- narration only.

THE RULE THIS FILE OBEYS, and the reason the repo is trustworthy: the model
never computes a number. It is handed the finished table from stats.py and
asked for the sentences around it. `_compact` deliberately strips the SQL and
the per-day basis detail before the prompt (the model does not need them and a
smaller prompt is a cheaper one), and format.py renders every figure from the
stats dict directly -- so a model that invents "add 40 vehicles" changes the
prose and cannot change the instruction.

`fallback_plan` is not a degraded mode bolted on afterwards: it is the
deterministic plan, written from the same table, and it is what ships whenever
there is no key, no langchain, or a failed call. Same schema, same formatter,
same numbers -- only the prose differs.
"""
from __future__ import annotations

import json
import logging
import os

from .schema import BandCall, FleetPlan

logger = logging.getLogger("trigger")

_SYSTEM = """You are a fleet planner writing for a Facilities Head.

You are given a COMPUTED table of next week's projected commute demand and the
vehicle change it implies, per day and shift band. Every number in it was
computed in Python from the company's own trip data.

Rules, without exception:
- NEVER invent, recompute or adjust a number. Quote only figures present in
  the table, and prefer describing them to repeating them.
- The recommendation is TWO-SIDED and both sides matter: ADD means the fleet
  would otherwise fall short and employees are stranded; RELEASE means
  vehicles are booked that nobody will ride and the money is spent anyway.
  Never silently drop one side.
- Where evidence is thin (few basis days, a screened anomalous day, a withheld
  day), say so plainly rather than sounding confident.
- Be short. A Facilities Head reads this on a phone before Monday.

{format_instructions}"""

_HUMAN = """Week beginning {week_start} (through {week_end}).

Computed fleet table:
{context}

Write the plan."""


def _compact(stats: dict) -> dict:
    """What the model sees: the decision table, without the SQL or the basis
    dates. Smaller prompt, same decisions -- and nothing the model could
    mistake for something it is meant to recompute."""
    days = []
    for d in stats["days"]:
        o = d["overall"]
        days.append({
            "date": d["date"], "weekday": d["weekday"],
            "projectedRiders": o["projectedRiders"],
            "interval": [o["intervalLow"], o["intervalHigh"]],
            "basisDaysUsed": o["basisDaysUsed"],
            "withheld": o["withheld"],
            "vehiclesWithBuffer": o["vehiclesWithBuffer"],
            "ranVehiclesWithBuffer": o["ranVehiclesWithBuffer"],
            "direction": o["direction"], "vehicleDelta": o["vehicleDelta"],
            "bands": [{
                "band": r["band"], "projectedRiders": r["projectedRiders"],
                "basisDaysUsed": r["basisDaysUsed"],
                "vehiclesWithBuffer": r["vehiclesWithBuffer"],
                "ranVehiclesWithBuffer": r["ranVehiclesWithBuffer"],
                "direction": r["direction"], "vehicleDelta": r["vehicleDelta"],
                "screened": [s["date"] for s in r["screenedBasisDays"]],
            } for r in d["byBand"]],
        })
    return {
        "weekStart": stats["weekStart"], "weekEnd": stats["weekEnd"],
        "method": stats["method"], "bufferPct": stats["bufferPct"],
        "totals": stats["totals"], "days": days,
    }


def _lenient_json(text: str) -> dict | None:
    """The first JSON object in the reply. Models wrap JSON in prose and
    fences; refusing on that costs a plan for a formatting habit."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def fallback_plan(stats: dict, reason: str) -> FleetPlan:
    """The deterministic plan. Written from the same computed table, so it is
    a real plan and not a placeholder -- the only thing the model would have
    added is nicer sentences."""
    t = stats["totals"]
    adds = [r for d in stats["days"] for r in d["byBand"] if r["direction"] == "ADD"]
    rels = [r for d in stats["days"] for r in d["byBand"] if r["direction"] == "RELEASE"]
    adds.sort(key=lambda r: -(r["vehicleDelta"] or 0))
    rels.sort(key=lambda r: (r["vehicleDelta"] or 0))

    headline = (f"Week of {stats['weekStart']}: "
                f"{t['vehiclesToAdd']} vehicle-days to add, "
                f"{t['vehiclesToRelease']} to release "
                f"across {t['daysProjected']} projected days.")

    caveats = []
    if t["daysWithheld"]:
        caveats.append(f"{t['daysWithheld']} day(s) had no projectable history "
                       f"and are reported as withheld rather than guessed.")
    if t["screenedBasisDays"]:
        caveats.append("Screened as anomalous and excluded from the baseline: "
                       + ", ".join(t["screenedBasisDays"]) + ".")
    thin = sorted({f"{r['date']} {r['band']}" for d in stats["days"]
                   for r in d["byBand"]
                   if r["thinEvidence"] and not r["withheld"]})
    if thin:
        caveats.append(f"{len(thin)} band-day(s) rest on fewer than the full "
                       f"four basis days: " + ", ".join(thin[:6])
                       + ("…" if len(thin) > 6 else "") + ".")

    return FleetPlan(
        headline=headline,
        demand_outlook=(
            f"Projected {t['projectedRiders']:.0f} rider-days across "
            f"{t['daysProjected']} of {stats['daysAhead']} days, by the "
            f"{stats['method']} baseline on {stats['metric']}."),
        add_where=[f"{r['date']} {r['band']}: +{r['vehicleDelta']} vehicles "
                   f"({r['ranVehiclesWithBuffer']} → {r['vehiclesWithBuffer']})"
                   for r in adds[:5]],
        release_where=[f"{r['date']} {r['band']}: {r['vehicleDelta']} vehicles "
                       f"({r['ranVehiclesWithBuffer']} → {r['vehiclesWithBuffer']})"
                       for r in rels[:5]],
        band_calls=[BandCall(day=r["date"], band=r["band"],
                             direction=r["direction"],
                             why=f"projected {r['projectedRiders']} riders/day")
                    for r in (adds[:3] + rels[:3])],
        evidence_caveats=caveats,
        recommended_actions=[
            "Confirm next week's vehicle booking with the vendors before the "
            "roster locks.",
            "Where the call is RELEASE, confirm the riders before releasing -- "
            "a released cab is not easily recovered mid-week.",
        ],
        reasoning=f"Deterministic plan — {reason}.",
    )


class _DirectChain:
    """The prompt-less path for an injected model: hand the inputs straight to
    it. Only reached when langchain is absent AND a model was injected (a
    test); the production path always goes through the real template."""

    def __init__(self, llm):
        self.llm = llm

    def invoke(self, inputs):
        return self.llm.invoke(inputs)


def build_chain(cfg, llm=None):
    """The LangChain pipeline, or (None, None) when it cannot be built.

    Two ways it cannot: no API key, or langchain not installed (it is in
    trigger/requirements.txt, not service/requirements.txt). Both return the
    deterministic plan rather than raising -- to a Facilities Head on a Sunday
    evening those are the same situation.
    """
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if llm is None and not api_key:
        return None, None
    try:
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        if llm is not None:
            # An INJECTED model must not depend on the optional package. This
            # is the seam the selftest uses to prove a model figure can never
            # reach the output, and a seam that only works when an optional
            # dependency happens to be installed is a seam that stops being
            # tested the moment it is not.
            return _DirectChain(llm), None
        logger.info("trigger: langchain not installed (%s), deterministic plan", exc.name)
        return None, None

    parser = PydanticOutputParser(pydantic_object=FleetPlan)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM), ("human", _HUMAN)]
    ).partial(format_instructions=parser.get_format_instructions())
    llm = llm or ChatOpenAI(
        model=cfg.model, base_url=cfg.base_url, api_key=api_key,
        temperature=cfg.temperature, max_tokens=cfg.max_tokens,
        timeout=120, max_retries=1,
    )
    return prompt | llm, parser


def plan(stats: dict, cfg, llm=None) -> tuple[FleetPlan, str]:
    """(plan, source) -- source is "langchain" or "fallback", so the Slack
    footer says which wrote it. Every failure path returns a real plan."""
    chain, parser = build_chain(cfg, llm)
    if chain is None:
        return fallback_plan(stats, "no model available"), "fallback"

    context = json.dumps(_compact(stats), indent=1)
    try:
        message = chain.invoke({
            "week_start": stats["weekStart"],
            "week_end": stats["weekEnd"],
            "context": context,
        })
        text = message.content if hasattr(message, "content") else str(message)
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    except Exception as exc:
        logger.warning("trigger: model call failed (%s), deterministic plan",
                       type(exc).__name__)
        return fallback_plan(stats, f"model call failed ({type(exc).__name__})"), "fallback"

    data = _lenient_json(text)
    if data is None:
        return fallback_plan(stats, "model reply was not JSON"), "fallback"
    try:
        return FleetPlan(**data), "langchain"
    except Exception as exc:
        logger.warning("trigger: model reply did not fit the schema (%s)",
                       type(exc).__name__)
        return fallback_plan(stats, "model reply did not fit the schema"), "fallback"
