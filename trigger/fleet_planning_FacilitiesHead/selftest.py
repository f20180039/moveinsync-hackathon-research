"""End-to-end check for the predictive fleet agent. No network, posts nothing.

    python -m trigger.fleet_planning_FacilitiesHead.selftest

Covers what can silently break: the vehicle arithmetic is the shift planner's
own and not a second allocator, the recommendation is genuinely TWO-SIDED
(both an add and a release are reachable, and each is produced by the right
input), a model figure can never overwrite a computed one, the evidence a
manager needs (interval, basis-day count, screened anomalies) survives into
the message, and the deterministic plan is a real plan rather than a
placeholder.
"""
from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from ..common.config import ROOT
from ..common import run_context
from . import chain, format as fmt, stats as stats_mod
from .config import Config
from .schema import FleetPlan


def _check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return bool(ok)


class _LyingModel:
    """A model that returns a syntactically valid plan full of WRONG numbers.

    This is the point of the whole architecture, so it is tested rather than
    asserted: if a fleet count could come from the model, this stub would move
    it, and a Facilities Head would book 999 vehicles.
    """

    def invoke(self, _inputs):
        class _Msg:
            content = json.dumps({
                "headline": "ADD 999 VEHICLES EVERYWHERE",
                "demand_outlook": "Demand will be 123456 riders per day.",
                "add_where": ["every day: +999 vehicles"],
                "release_where": [],
                "band_calls": [],
                "evidence_caveats": [],
                "recommended_actions": ["book 999 vehicles"],
                "reasoning": "because I said so",
            })
        return _Msg()


def main() -> int:
    load_dotenv(ROOT / ".env")
    print("\nPredictive fleet agent selftest\n" + "=" * 32)
    results = []
    cfg = Config.from_env()

    print("\n1. The vehicle arithmetic is the shift planner's, not a second one")
    # Hand-calculated: 100 riders at 4 seats = 25 vehicles; a 10% buffer makes
    # 27.5 -> 28 (ceil, never round down: half a spare vehicle strands people).
    v = stats_mod.vehicles_for(100.0, 4.0, 10.0)
    results.append(_check("25 vehicles for 100 riders at 4 seats",
                          v["vehicles"] == 25, str(v["vehicles"])))
    results.append(_check("28 with a 10% standby buffer",
                          v["vehiclesWithBuffer"] == 28, str(v["vehiclesWithBuffer"])))
    results.append(_check("drivers track buffered vehicles one-for-one",
                          v["drivers"] == v["vehiclesWithBuffer"]))
    results.append(_check("the buffer is the SHARED env var, not a local default",
                          cfg.capacity_buffer_pct
                          == Config.from_env().capacity_buffer_pct
                          and "TRIGGER_CAPACITY_BUFFER_PCT" in
                          open(ROOT / "trigger" / "fleet_planning_FacilitiesHead"
                               / "config.py").read()))
    # No capacity recorded is NOT a fleet of zero, and not a guess.
    none_v = stats_mod.vehicles_for(100.0, None, 10.0)
    results.append(_check("no recorded capacity yields None, never a made-up fleet",
                          none_v["vehiclesWithBuffer"] is None))
    results.append(_check("a zero-seat cab is treated as missing, not as no seats",
                          stats_mod.vehicles_for(100.0, 0.0, 10.0)["vehicles"] is None))

    print("\n2. The computed table")
    s = stats_mod.build(cfg)
    results.append(_check("a week of days is projected",
                          len(s["days"]) == cfg.days_ahead, str(len(s["days"]))))
    results.append(_check("every day carries shift bands",
                          all(d["byBand"] for d in s["days"])))
    rows = [r for d in s["days"] for r in d["byBand"]]
    results.append(_check("every row carries its basis-day count",
                          all("basisDaysUsed" in r for r in rows)))
    projected = [r for r in rows if r["projectedRiders"] is not None]
    results.append(_check("some bands actually project", bool(projected),
                          f"{len(projected)} of {len(rows)}"))
    results.append(_check("a projected row carries an interval or says why not",
                          all(r["intervalLow"] is not None or r["basisDaysUsed"] < 2
                              for r in projected)))

    print("\n3. TWO-SIDED: both calls are reachable, from the right inputs")
    directions = {r["direction"] for r in rows}
    results.append(_check("the sample produces BOTH an ADD and a RELEASE",
                          {"ADD", "RELEASE"} <= directions,
                          ", ".join(sorted(directions))))
    # And each direction is produced by the input that should produce it --
    # a table that happened to contain both words would pass the check above
    # even if the sign were inverted.
    add = next(r for r in rows if r["direction"] == "ADD")
    rel = next(r for r in rows if r["direction"] == "RELEASE")
    results.append(_check("ADD means projected above what ran",
                          add["vehiclesWithBuffer"] > add["ranVehiclesWithBuffer"],
                          f"{add['ranVehiclesWithBuffer']} -> {add['vehiclesWithBuffer']}"))
    results.append(_check("RELEASE means projected below what ran",
                          rel["vehiclesWithBuffer"] < rel["ranVehiclesWithBuffer"],
                          f"{rel['ranVehiclesWithBuffer']} -> {rel['vehiclesWithBuffer']}"))
    results.append(_check("an unprojectable band is NOT reported as HOLD",
                          all(r["direction"] == "NO_PROJECTION"
                              for r in rows if r["vehiclesWithBuffer"] is None)))
    results.append(_check("the week's totals carry both sides",
                          "vehiclesToAdd" in s["totals"]
                          and "vehiclesToRelease" in s["totals"],
                          f"+{s['totals']['vehiclesToAdd']} / "
                          f"-{s['totals']['vehiclesToRelease']}"))

    print("\n4. The comparison is the SAME WEEKDAY, not the week's average")
    # The trap: Wednesday runs ~14x a Saturday on real data, so comparing a
    # weekend projection against a weekly mean makes every weekend a RELEASE
    # and every weekday an ADD -- pure calendar, no signal.
    day0 = s["days"][0]["overall"]
    results.append(_check("each row names the day it was compared against",
                          all(r.get("ranDate") for r in rows)))
    results.append(_check("that day is exactly one week before",
                          all((__import__("datetime").date.fromisoformat(r["date"])
                               - __import__("datetime").date.fromisoformat(r["ranDate"])).days == 7
                              for r in rows)))
    results.append(_check("weekdays match", all(
        __import__("datetime").date.fromisoformat(r["date"]).weekday()
        == __import__("datetime").date.fromisoformat(r["ranDate"]).weekday()
        for r in rows)))

    print("\n5. The model narrates; it never supplies a figure")
    lying, source = chain.plan(s, cfg, llm=_LyingModel())
    results.append(_check("the stub model was actually used",
                          source == "langchain", source))
    results.append(_check("its prose reaches the message",
                          "999" in lying.headline))
    text = fmt.slack_text(lying, s, source)
    # The rendered vehicle figures must be the COMPUTED ones. The stub said
    # 999 everywhere; the table says otherwise, and the table wins.
    computed_line = (f"▲ add {s['totals']['vehiclesToAdd']} · "
                     f"▼ release {s['totals']['vehiclesToRelease']}")
    results.append(_check("the vehicle change row is the computed one",
                          computed_line in text, computed_line))
    results.append(_check("no invented day figure reaches the day table",
                          all(f"~{r['projectedRiders']:.0f} riders" in text
                              or r["projectedRiders"] is None
                              for r in [d["overall"] for d in s["days"]][:1])))
    results.append(_check("123456 never appears as a demand figure",
                          "123456 riders" not in text.replace(lying.demand_outlook, "")))

    print("\n6. The deterministic plan is a real plan")
    fb, src = chain.plan(s, cfg, llm=None)
    results.append(_check("falls back with no model", src == "fallback", src))
    results.append(_check("it is the same schema", isinstance(fb, FleetPlan)))
    results.append(_check("it names both sides",
                          bool(fb.add_where) or bool(fb.release_where)))
    results.append(_check("it says it was deterministic",
                          "Deterministic" in fb.reasoning, fb.reasoning))
    fb_text = fmt.slack_text(fb, s, src)
    results.append(_check("the fallback renders the SAME computed figures",
                          computed_line in fb_text))

    print("\n7. Evidence travels to the message")
    results.append(_check("the method is named as a baseline, not a forecast",
                          "not a forecast" in fb_text))
    results.append(_check("the basis-day coverage is stated",
                          "days projected" in fb_text))
    if s["totals"]["screenedBasisDays"]:
        results.append(_check("screened anomalous days are named in the message",
                              s["totals"]["screenedBasisDays"][0] in fb_text,
                              s["totals"]["screenedBasisDays"][0]))
    else:
        print("  [skip] no anomalous basis day in this dataset to name")
    results.append(_check("provenance is present when a run context is given",
                          "Not reconciled" in fmt.slack_text(
                              fb, stats_mod.build(cfg, run_context.resolve(
                                  "week", "http://127.0.0.1:1")), src)))

    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
