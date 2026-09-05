"""End-to-end check for the Facilities Head agent. No network, posts nothing.

    python -m trigger.vendor_strategy_Facilities_Head.selftest

Runs all three windows against the real dataset and then walks the eight edge
cases the brief calls for, including the two that matter most: a high-cost
vendor must not be called bad value automatically, and a cheap one must not
be called good value automatically.
"""
from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from ..common import data as data_mod
from ..common.config import ROOT
from . import analysis, periods, report
from . import scorecard as sc
from .config import Config
from .daily import run as daily
from .metrics import totals as totals_of
from .monthly import run as monthly
from .quarterly import run as quarterly
from .schema import DailyBrief, MonthlyReview, QuarterExecutive, VendorStrategy

STUBS = {
    DailyBrief: {"overall_status": "WATCH", "headline": "Stub daily headline.",
                 "what_went_well": ["a"], "what_went_poorly": ["b"], "anomalies": [],
                 "vendors_needing_attention": [], "recommended_actions": ["c"]},
    MonthlyReview: {"overall_status": "WATCH", "headline": "Stub monthly headline.",
                    "best_performers": [], "underperformers": [], "improving": [],
                    "deteriorating": [], "cost_observations": ["d"],
                    "systemic_vs_isolated": "isolated", "management_actions": ["e"]},
}


def _check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def _fake(model_cls, payload):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    return FakeListChatModel(responses=[json.dumps(payload)] * 40)


def _exploding():
    from langchain_core.runnables import RunnableLambda

    def boom(_i):
        raise ConnectionError("selftest: simulated outage")
    return RunnableLambda(boom)


def _vendor(**over) -> dict:
    """A synthetic vendor for the edge cases -- shaped exactly like a row
    `metrics.py` produces, so it exercises the real scoring code."""
    base = dict(vendor="V", trips=100, activeDays=20, completed=100, completionPct=100.0,
                onTime=95, onTimePct=95.0, slaAdherencePct=98.0, avgDelayMin=2.0,
                p90DelayMin=4.0, maxDelayMin=30.0, delayedTripPct=5.0,
                driverAttributedDelays=1, driverNonCompliance=0, cabNonCompliance=0,
                plannedRiders=300, actualRiders=290, noShowRiders=6, noShowPct=2.0,
                cancelledBookings=0, avgOccupancy=0.6, alerts=1, alertsPer100Trips=1.0,
                severeAlerts=0, routeRating=4.5, driverRating=4.5, safetyRating=4.6,
                ratingResponses=40, totalCost=120000.0, costCoveragePct=100.0,
                costPerTrip=1200.0, costPerOnTimeTrip=1263.0, costPerKm=80.0,
                costOnBreachedTrips=0.0, km=1500.0, onTimeByDay=[],
                onTimeVolatility=4.0, poorDays=0, ratedDays=20)
    base.update(over)
    return base


def _scored(v, cfg, peer_cost=1300.0, peer_service=90.0):
    v["scores"] = {"service": sc.service_score(v),
                   "reliability": sc.reliability_score(v, cfg)[0],
                   "costValue": sc.cost_value_score(v, peer_cost)[0]}
    parts = [(cfg.w_service, v["scores"]["service"]),
             (cfg.w_reliability, v["scores"]["reliability"])]
    if v["scores"]["costValue"] is not None:
        parts.append((cfg.w_cost, v["scores"]["costValue"]))
    tw = sum(w for w, _ in parts)
    v["scores"]["overall"] = round(sum(w * x for w, x in parts) / tw, 1)
    v["quadrant"] = sc.value_quadrant(v, peer_cost, peer_service)
    return v


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = Config.from_env()
    results = []
    con, health = data_mod.connect(cfg.data_dir)

    print(f"\n1. Windows resolved from the data ({cfg.data_dir})")
    months = periods.months_present(con)
    day = periods.day_window(con, cfg)
    month = periods.month_window(con, cfg)
    quarter = periods.quarter_window(con, cfg)
    results.append(_check("months present", len(months) >= 3, ", ".join(months)))
    results.append(_check("day / month / quarter all resolve",
                          all([day.label, month.label, quarter.label]),
                          f"{day.label} · {month.label} · {quarter.label}"))
    results.append(_check("quarter states which quarter it is",
                          bool(quarter.note) and len(quarter.sub_labels) == 3,
                          quarter.note[:58]))

    print("\n2. Deterministic engine over the quarter")
    qmonths = periods.month_windows(con, cfg, quarter.sub_labels)
    board = sc.build(con, quarter, qmonths, cfg)
    totals = totals_of(board["vendors"])
    results.append(_check("many vendors analysed, not one",
                          len(board["vendors"]) >= 5,
                          f"{len(board['vendors'])} vendors, {len(board['ranked'])} ranked"))
    overall = [v["scores"]["overall"] for v in board["ranked"]]
    results.append(_check("ranked best-first", overall == sorted(overall, reverse=True)))
    results.append(_check("every ranked vendor has a verdict and confidence",
                          all(v["recommendationFloor"] in sc.RECOMMENDATIONS
                              and v["confidence"] in ("LOW", "MEDIUM", "HIGH")
                              for v in board["ranked"])))
    trends = {v["trend"]["onTimeTrend"] for v in board["ranked"]}
    results.append(_check("trends are measured across months, not averaged away",
                          len(trends) >= 2, ", ".join(sorted(trends))))
    results.append(_check("programme totals computed",
                          totals["trips"] > 0 and totals["totalCost"] is not None,
                          f"{totals['trips']} trips, {report.money(totals['totalCost'])}"))

    print("\n3. Edge cases")
    excellent = _scored(_vendor(onTimePct=99.0, slaAdherencePct=100.0,
                                onTimeVolatility=1.0, costPerOnTimeTrip=1000.0), cfg)
    poor = _scored(_vendor(onTimePct=68.0, slaAdherencePct=75.0, completionPct=92.0,
                           onTimeVolatility=22.0, poorDays=12, noShowPct=9.0,
                           alertsPer100Trips=6.0, costPerOnTimeTrip=1900.0), cfg)
    results.append(_check("1. an excellent vendor scores high",
                          excellent["scores"]["overall"] >= 75,
                          f"{excellent['scores']['overall']}"))
    results.append(_check("2. a poor vendor scores low",
                          poor["scores"]["overall"] < 60, f"{poor['scores']['overall']}"))

    dear_good = _scored(_vendor(onTimePct=98.0, slaAdherencePct=99.0,
                                onTimeVolatility=2.0, costPerOnTimeTrip=1800.0), cfg)
    cheap_bad = _scored(_vendor(onTimePct=70.0, slaAdherencePct=78.0,
                                onTimeVolatility=20.0, poorDays=10,
                                costPerOnTimeTrip=700.0), cfg)
    results.append(_check("3. high cost + strong service is NOT called poor value",
                          dear_good["quadrant"] == sc.PREFERRED, dear_good["quadrant"]))
    results.append(_check("4. low cost + weak service is NOT called good value",
                          cheap_bad["quadrant"] == sc.BACKUP
                          and cheap_bad["scores"]["overall"] < dear_good["scores"]["overall"],
                          f"{cheap_bad['quadrant']}, "
                          f"{cheap_bad['scores']['overall']} vs {dear_good['scores']['overall']}"))

    declining = sc._trend_of([95.0, 91.0, 83.0], 2.0)
    flat_avg = round(sum([95.0, 91.0, 83.0]) / 3, 1)
    results.append(_check("5. a deteriorating vendor is caught despite a healthy average",
                          declining == sc.DETERIORATING,
                          f"95→91→83 reads {declining}, average would read {flat_avg}"))

    no_cost = _vendor(costPerOnTimeTrip=None, totalCost=None, costCoveragePct=0.0)
    score, caveat = sc.cost_value_score(no_cost, 1300.0)
    no_cost = _scored(no_cost, cfg)
    results.append(_check("6. missing cost data is stated, not guessed",
                          score is None and caveat is not None
                          and no_cost["quadrant"] == sc.UNKNOWN_VALUE,
                          no_cost["quadrant"]))
    verdict = quarterly.deterministic_verdict(
        dict(no_cost, trend={"onTimeTrend": sc.STABLE, "costTrend": sc.INSUFFICIENT,
                             "onTimeChangePP": None, "costChangePct": None,
                             "labels": [], "onTimeSeries": [], "costPerOnTimeSeries": []},
             rank=1, recommendationFloor=sc.CONTINUE_PLAIN, confidence="MEDIUM",
             evidence=["e"]), "selftest")
    results.append(_check("   and the verdict says so out loud",
                          "cannot be assessed on price" in verdict.value_for_money))

    thin = _vendor(onTimePct=None, slaAdherencePct=None, completionPct=None,
                   routeRating=None, driverRating=None, safetyRating=None,
                   ratingResponses=0, onTimeVolatility=None, ratedDays=0,
                   costPerOnTimeTrip=None)
    rel, rel_caveat = sc.reliability_score(thin, cfg)
    results.append(_check("7. a vendor with missing performance fields does not crash",
                          sc.service_score(thin) == 0.0 and rel_caveat is not None,
                          rel_caveat))

    a = _scored(_vendor(onTimePct=94.0, onTimeVolatility=3.0, costPerOnTimeTrip=1400.0), cfg)
    b = _scored(_vendor(onTimePct=94.0, onTimeVolatility=12.0, costPerOnTimeTrip=1150.0), cfg)
    results.append(_check("8. near-identical vendors differ on the dimensions",
                          abs(a["scores"]["overall"] - b["scores"]["overall"]) < 6
                          and a["scores"]["reliability"] != b["scores"]["reliability"]
                          and a["scores"]["costValue"] != b["scores"]["costValue"],
                          f"A {a['scores']['overall']} vs B {b['scores']['overall']}; "
                          f"reliability {a['scores']['reliability']}/{b['scores']['reliability']}, "
                          f"cost {a['scores']['costValue']}/{b['scores']['costValue']}"))

    print("\n4. LangChain — the guards on what the model may decide")
    worst = board["ranked"][-1]
    stub = VendorStrategy(vendor="WRONG NAME", overall_assessment="x",
                          recommendation="CONTINUE — INCREASE ALLOCATION",
                          confidence="HIGH", value_for_money="x",
                          performance_trend="x", recommended_action="x")
    guarded = quarterly._guard(stub, worst)
    results.append(_check("the verdict is re-bound to the right vendor",
                          guarded.vendor == worst["vendor"]))
    results.append(_check("the model cannot jump the recommendation ladder",
                          abs(quarterly._LADDER.index(guarded.recommendation)
                              - quarterly._LADDER.index(worst["recommendationFloor"])) <= 1,
                          f"floor {worst['recommendationFloor']} → {guarded.recommendation}"))
    results.append(_check("the model cannot claim more confidence than the evidence",
                          quarterly._CONF[guarded.confidence]
                          <= quarterly._CONF[worst["confidence"]],
                          f"asked HIGH, evidence {worst['confidence']}, got {guarded.confidence}"))
    junk = quarterly._guard(stub.model_copy(update={"recommendation": "FIRE THEM"}), worst)
    results.append(_check("a verdict outside the vocabulary falls back to the floor",
                          junk.recommendation == worst["recommendationFloor"]))

    print("\n5. Each trigger, end to end (stubbed model, no network)")
    dboard = sc.build(con, day, [], cfg, min_trips=cfg.min_trips_daily)
    dtotals = totals_of(dboard["vendors"])
    dres, dsrc = analysis._invoke(analysis._DAILY_SYSTEM,
                                 [analysis.daily_context(day, dboard, dtotals)],
                                 DailyBrief, cfg, llm=_fake(DailyBrief, STUBS[DailyBrief]))
    dtexts = daily.format_message(day, dres[0], dboard, dtotals, dsrc)
    results.append(_check("daily builds a message", dsrc == "langchain" and bool(dtexts),
                          f"{len(dtexts)} message(s)"))

    mboard = sc.build(con, month, periods.thirds(month), cfg)
    mtotals = totals_of(mboard["vendors"])
    mres, msrc = analysis._invoke(analysis._MONTHLY_SYSTEM,
                                  [analysis.monthly_context(month, mboard, mtotals)],
                                  MonthlyReview, cfg,
                                  llm=_fake(MonthlyReview, STUBS[MonthlyReview]))
    mtexts = monthly.format_message(month, mres[0], mboard, mtotals, msrc)
    results.append(_check("monthly builds a message with a scorecard",
                          bool(mtexts) and "VENDOR SCORECARD" in "\n".join(mtexts)))

    verdicts = [quarterly.deterministic_verdict(v, "selftest") for v in board["ranked"]]
    ex = quarterly.exec_fallback(board, totals, verdicts)
    qtexts = quarterly.format_message(quarter, ex, verdicts, board, totals, "fallback")
    joined = "\n".join(qtexts)
    results.append(_check("quarterly builds the strategic review",
                          all(s in joined for s in ("VENDOR RANKING", "VENDOR VERDICTS",
                                                    "NEXT-QUARTER VENDOR STRATEGY",
                                                    "STRATEGIC RISKS")),
                          f"{len(qtexts)} message(s)"))
    results.append(_check("every ranked vendor lands in exactly one strategy bucket",
                          sum(len(v) for v in ex.next_quarter_strategy.model_dump().values())
                          == len(board["ranked"])))

    print("\n6. Model failure")
    fres, fsrc = analysis._invoke(analysis._DAILY_SYSTEM,
                                  [analysis.daily_context(day, dboard, dtotals)],
                                  DailyBrief, cfg, llm=_exploding())
    fb = fres[0] or daily.fallback(dboard, dtotals, "selftest outage")
    results.append(_check("an unreachable model still produces a report",
                          fsrc == "fallback" and isinstance(fb, DailyBrief)))

    print("\n7. Slack payload (captured, not sent)")
    captured = _capture_slack(qtexts[0])
    results.append(_check("payload is {'text': ...}",
                          captured.get("json", {}).keys() == {"text"}))
    from ..common.slack import MAX_CHARS
    results.append(_check("every part fits Slack's limit",
                          all(len(t) <= MAX_CHARS + 60 for t in qtexts),
                          ", ".join(str(len(t)) for t in qtexts)))
    # The report's own caveat NAMES these things to say the dataset lacks
    # them, so scan the body with that sentence removed -- otherwise the
    # disclaimer trips the check it exists to satisfy.
    body = joined.replace("The dataset carries no contracted SLA targets, contract "
                          "terms or complaint tickets, so none are referenced.", "")
    results.append(_check("no fabricated SLA, penalty or complaint language in the body",
                          not any(w in body.lower() for w in
                                  ("contracted sla", "sla target of", "penalty clause",
                                   "complaint ticket", "per the contract"))))

    con.close()
    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if all(results) else 1


def _capture_slack(text: str) -> dict:
    import httpx
    from signaldesk import delivery
    seen: dict = {}
    real_post, real_url = httpx.post, delivery.os.environ.get("SLACK_WEBHOOK_URL")

    def fake_post(url, **kwargs):
        seen.update({"url": url, **kwargs})
        return httpx.Response(200, request=httpx.Request("POST", url))

    httpx.post = fake_post
    delivery.os.environ["SLACK_WEBHOOK_URL"] = real_url or "https://hooks.slack.test/selftest"
    try:
        delivery.slack_send(text)
    finally:
        httpx.post = real_post
        if real_url is None:
            delivery.os.environ.pop("SLACK_WEBHOOK_URL", None)
    return seen


if __name__ == "__main__":
    sys.exit(main())
