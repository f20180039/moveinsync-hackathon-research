"""QUARTERLY trigger — the strategic vendor review. The important one.

    python -m trigger.vendor_strategy_Facilities_Head.quarterly.run --dry-run
    python -m trigger.vendor_strategy_Facilities_Head.quarterly.run --quarter 2026Q2

Answers, per vendor and with evidence: continue, prefer, monitor, review,
reduce or replace — and for the programme: what the next quarter's vendor
strategy should be.

Two rounds of reasoning, both LangChain:
  1. one INDEPENDENT call per vendor → VendorStrategy
  2. one call over those verdicts   → QuarterExecutive

Vendors outside the reasoning window (top `--top` plus the weakest `--bottom`)
keep their deterministic verdict, so every vendor still appears in the
strategy — the model's attention goes where decisions actually get made.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from ...common import config as _cfg          # noqa: F401  -- service/ on sys.path
from ...common import data as data_mod, slack
from ...common.config import ROOT
from .. import analysis, periods, report
from ..config import Config
from ..metrics import totals as totals_of
from ..schema import (NextQuarterStrategy, QuarterExecutive, VendorStrategy)
from .. import scorecard as sc

logger = logging.getLogger("trigger")

# Best → worst. Used to stop the model moving a verdict more than one notch
# away from what the deterministic model concluded.
_LADDER = [sc.CONTINUE_INCREASE, sc.CONTINUE_PREFER, sc.CONTINUE_PLAIN,
           sc.MONITOR, sc.REVIEW, sc.REDUCE, sc.REPLACE]
_CONF = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def deterministic_verdict(v: dict, reason: str) -> VendorStrategy:
    """A full verdict with no model at all — same schema, so the report is
    identical in structure whether the model answered or not."""
    t = v["trend"]
    strengths, concerns = [], []
    if v["onTimePct"] is not None and v["onTimePct"] >= 95:
        strengths.append(f"on-time {v['onTimePct']}% across {v['trips']} trips")
    if v["scores"]["reliability"] >= 85:
        strengths.append(f"consistent day to day (reliability {v['scores']['reliability']:.0f})")
    if v["scores"]["costValue"] is not None and v["scores"]["costValue"] >= 60:
        strengths.append(f"cost per on-time trip {report.money(v['costPerOnTimeTrip'])}, "
                         f"below the peer median")
    if t["onTimeTrend"] == sc.DETERIORATING:
        concerns.append(f"on-time fell {t['onTimeChangePP']} pp across the quarter")
    if t["costTrend"] == sc.DETERIORATING and t["costChangePct"] is not None:
        concerns.append(f"cost per on-time trip rose {t['costChangePct']}%")
    if v["poorDays"]:
        concerns.append(f"{v['poorDays']} of {v['ratedDays']} rated days below the "
                        f"poor-day line")
    if v["severeAlerts"]:
        concerns.append(f"{v['severeAlerts']} severe alert(s)")

    if v["costPerOnTimeTrip"] is None:
        value = ("Cost data is not available for this vendor in the quarter, so "
                 "value for money cannot be assessed on price.")
    else:
        value = (f"{v['quadrant'].lower()} — cost per on-time trip "
                 f"{report.money(v['costPerOnTimeTrip'])} against a peer median, "
                 f"with a service score of {v['scores']['service']:.0f}.")
    return VendorStrategy(
        vendor=v["vendor"],
        overall_assessment=(f"Score {v['scores']['overall']:.0f}/100"
                            + (f", rank {v['rank']}" if v.get("rank") else "")
                            + f", on {v['trips']} trips."),
        recommendation=v["recommendationFloor"],
        confidence=v["confidence"],
        key_strengths=strengths or ["no standout strength in the metrics"],
        key_concerns=concerns or ["no material concern in the metrics"],
        value_for_money=value,
        performance_trend=(f"on-time {t['onTimeTrend'].lower()}"
                           + (f" ({t['onTimeChangePP']:+.1f} pp)"
                              if t["onTimeChangePP"] is not None else "")),
        recommended_action=f"Apply the {v['recommendationFloor'].lower()} decision.",
        evidence=v["evidence"] + [f"deterministic verdict only ({reason})"],
    )


def _guard(s: VendorStrategy, v: dict) -> VendorStrategy:
    """Re-assert what the model is not allowed to decide: whose verdict this
    is, how far it may move it, and how sure it may claim to be."""
    rec = s.recommendation.strip().upper()
    floor = v["recommendationFloor"]
    if rec not in _LADDER:
        rec = floor
    else:
        want, have = _LADDER.index(rec), _LADDER.index(floor)
        if abs(want - have) > 1:
            rec = _LADDER[have + (1 if want > have else -1)]
            logger.info("quarterly: %s — model wanted %s, floor %s; clamped to %s",
                        v["vendor"], s.recommendation, floor, rec)
    conf = s.confidence.strip().upper()
    if conf not in _CONF or _CONF[conf] > _CONF[v["confidence"]]:
        conf = v["confidence"]
    return s.model_copy(update={"vendor": v["vendor"], "recommendation": rec,
                                "confidence": conf})


def _strategy_lists(verdicts, board) -> NextQuarterStrategy:
    """Built from the FINAL verdicts, deterministically — so the strategy
    lists can never disagree with the per-vendor recommendations above them."""
    buckets = {sc.CONTINUE_INCREASE: "increase_allocation",
               sc.CONTINUE_PREFER: "maintain", sc.CONTINUE_PLAIN: "maintain",
               sc.MONITOR: "monitor", sc.REVIEW: "commercial_review",
               sc.REDUCE: "commercial_review", sc.REPLACE: "potential_replacement"}
    out = {k: [] for k in ("increase_allocation", "maintain", "monitor",
                           "commercial_review", "potential_replacement")}
    for x in verdicts:
        out[buckets.get(x.recommendation, "monitor")].append(x.vendor)
    return NextQuarterStrategy(**out)


def exec_fallback(board, totals, verdicts) -> QuarterExecutive:
    ranked = board["ranked"]
    declining = [v for v in ranked if v["trend"]["onTimeTrend"] == sc.DETERIORATING]
    best_value = next((v["vendor"] for v in ranked
                       if v["quadrant"] in (sc.STRATEGIC, sc.PREFERRED)), "n/a")
    worst = ranked[-1]["vendor"] if ranked else "n/a"
    top3 = sum(v["trips"] for v in ranked[:3])
    risks = []
    if totals["trips"]:
        share = round(100.0 * top3 / totals["trips"], 1)
        if share >= 40:
            risks.append(f"Concentration: the top 3 vendors carry {share}% of trips.")
    for v in declining[:2]:
        risks.append(f"{v['vendor']}: on-time fell {v['trend']['onTimeChangePP']} pp "
                     f"across the quarter.")
    return QuarterExecutive(
        overall_status="NEEDS ATTENTION" if len(declining) >= 3 else
                       "WATCH" if declining else "GOOD",
        key_finding=(f"{len(declining)} of {len(ranked)} ranked vendors declined "
                     f"across the quarter; programme on-time "
                     f"{report.pct(totals['onTimePct'])} on {totals['trips']} trips."),
        best_performer=ranked[0]["vendor"] if ranked else "n/a",
        best_value_for_money=best_value,
        vendor_requiring_review=worst,
        strategic_risks=risks or ["No concentration or trend risk stands out."],
        next_quarter_strategy=_strategy_lists(verdicts, board),
        top_reasons=["Deterministic summary only (model unavailable)."],
        confidence="MEDIUM",
    )


def format_message(window, ex: QuarterExecutive, verdicts, board, totals, source):
    icon = report.STATUS_ICON.get(ex.overall_status, "🟡")
    head = [
        f"🏢 *QUARTERLY VENDOR STRATEGY REVIEW* · {window.label}",
        "Facilities Operations",
        "",
        f"*Overall vendor performance:* {icon} {ex.overall_status}",
        f"{totals['vendors']} vendors · {totals['trips']} trips · "
        f"on-time {report.pct(totals['onTimePct'])} · spend {report.money(totals['totalCost'])}",
        f"Best performer: *{ex.best_performer}* · Best value: *{ex.best_value_for_money}* · "
        f"Needs review: *{ex.vendor_requiring_review}*",
        "",
        f"*Key finding:* {ex.key_finding}",
    ]
    blocks = []

    ranking = ["🏆 *VENDOR RANKING*"]
    by_vendor = {x.vendor: x for x in verdicts}
    for v in board["ranked"][:6]:
        x = by_vendor.get(v["vendor"])
        rec = x.recommendation if x else v["recommendationFloor"]
        ranking.append(f"{report.REC_ICON.get(rec, '•')} *{v['rank']}. {v['vendor']} — "
                       f"{v['scores']['overall']:.0f}/100*  ·  {rec}")
        ranking.append(f"    {report.vendor_headline(v)}")
        ranking.append(f"    trend: {report.TREND_ICON.get(v['trend']['onTimeTrend'], '')}"
                       + (f" ({v['trend']['onTimeChangePP']:+.1f} pp)"
                          if v["trend"]["onTimeChangePP"] is not None else "")
                       + (f" · cost {v['trend']['costChangePct']:+.1f}%"
                          if v["trend"]["costChangePct"] is not None else ""))
    blocks.append("\n".join(ranking))

    detail = ["🔎 *VENDOR VERDICTS*"]
    for x in verdicts[:4]:
        detail.append(f"*{x.vendor}* — {x.recommendation} (confidence {x.confidence})")
        detail.append(f"    {x.overall_assessment}")
        if x.key_concerns:
            detail.append(f"    Concerns: {x.key_concerns[0]}")
        detail.append(f"    Value: {x.value_for_money}")
        detail.append(f"    Action: {x.recommended_action}")
        if x.evidence:
            detail.append(f"    Evidence: {'; '.join(x.evidence[:3])}")
    blocks.append("\n".join(detail))

    b = report.bullets("⚠️ STRATEGIC RISKS", ex.strategic_risks, 5)
    if b:
        blocks.append("\n".join(b))

    s = ex.next_quarter_strategy
    strat = ["🧠 *NEXT-QUARTER VENDOR STRATEGY*"]
    for label, names in (("Increase allocation", s.increase_allocation),
                         ("Maintain", s.maintain), ("Monitor", s.monitor),
                         ("Commercial review", s.commercial_review),
                         ("Potential replacement", s.potential_replacement)):
        if names:
            strat.append(f"*{label}:* {', '.join(names[:6])}"
                         + (f" (+{len(names) - 6} more)" if len(names) > 6 else ""))
    strat.append(f"\n*Confidence:* {ex.confidence}")
    if ex.top_reasons:
        strat.append("*Why:*\n" + "\n".join(f"• {r}" for r in ex.top_reasons[:5]))
    blocks.append("\n".join(strat))

    footer = ("_" + " ".join(report.data_caveats(board, totals))
              + f" Scoring: {analysis.SCORING_NOTE} Written by: {source}._")
    return slack.chunk("\n".join(head), blocks, footer)


def run(argv=None) -> int:
    p = argparse.ArgumentParser(description="Quarterly vendor strategy → Slack")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--quarter", help='e.g. 2026Q2; default is the last 3 months present')
    p.add_argument("--top", type=int, default=5, help="strongest vendors sent to the model")
    p.add_argument("--bottom", type=int, default=3, help="weakest vendors sent to the model")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    if args.quarter:
        os.environ["VENDOR_QUARTER"] = args.quarter
    cfg = Config.from_env()

    con, health = data_mod.connect(cfg.data_dir)
    try:
        window = periods.quarter_window(con, cfg)
        logger.info("trigger: quarterly review for %s — %s", window.label, window.note)
        months = periods.month_windows(con, cfg, window.sub_labels)
        board = sc.build(con, window, months, cfg)
        if not board["ranked"]:
            print(f"\nNo rankable vendor activity in {window.label}\n")
            return 0
        totals = totals_of(board["vendors"])
        logger.info("trigger: %d vendors (%d ranked) over %d months, %d trips",
                    totals["vendors"], len(board["ranked"]), len(months), totals["trips"])

        ranked = board["ranked"]
        chosen = ranked[:args.top] + [v for v in ranked[-args.bottom:]
                                      if v not in ranked[:args.top]]
        logger.info("trigger: reasoning over %d of %d ranked vendors "
                    "(top %d + weakest %d)", len(chosen), len(ranked),
                    args.top, args.bottom)

        parsed, source = analysis._invoke(
            analysis._QUARTER_VENDOR_SYSTEM,
            [analysis.quarter_vendor_context(window, v, board, totals) for v in chosen],
            VendorStrategy, cfg)
        verdicts = [_guard(p, v) if p else deterministic_verdict(v, "model unavailable")
                    for p, v in zip(parsed, chosen)]
        covered = {x.vendor for x in verdicts}
        verdicts += [deterministic_verdict(v, "outside the reasoning window")
                     for v in ranked if v["vendor"] not in covered]
        verdicts.sort(key=lambda x: next(
            (v["rank"] for v in ranked if v["vendor"] == x.vendor), 999))
        logger.info("trigger: %d vendor verdicts (%s)", len(verdicts), source)

        ex_parsed, ex_source = analysis._invoke(
            analysis._QUARTER_EXEC_SYSTEM,
            [analysis.quarter_exec_context(window, board, totals, verdicts)],
            QuarterExecutive, cfg)
        ex = ex_parsed[0] or exec_fallback(board, totals, verdicts)
        # The strategy lists are always rebuilt from the final verdicts, so a
        # model-written list can never contradict the recommendations above it.
        ex = ex.model_copy(update={"next_quarter_strategy":
                                   _strategy_lists(verdicts, board)})
        overall_source = source if source == ex_source else "mixed"

        texts = format_message(window, ex, verdicts, board, totals, overall_source)
        for t in texts:
            print("\n" + t + "\n")
        if args.json:
            print(json.dumps({"executive": ex.model_dump(),
                              "verdicts": [x.model_dump() for x in verdicts]}, indent=1))
        if args.dry_run or cfg.dry_run:
            logger.info("trigger: dry run, not posting to Slack")
            return 0
        sent = slack.send_all(texts)
        return 0 if all(r.delivered for r in sent) else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(run())
