"""MONTHLY trigger — month-end vendor performance review.

    python -m trigger.vendor_strategy_Facilities_Head.monthly.run --dry-run
    python -m trigger.vendor_strategy_Facilities_Head.monthly.run --month 2026-06

This does NOT concatenate daily reports. It goes back to the trips, bills,
alerts and feedback for the whole month and aggregates from scratch, then
splits the month into thirds to see which way each vendor moved inside it.
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
from ..schema import MonthlyReview, VendorNote
from .. import scorecard as sc

logger = logging.getLogger("trigger")


def fallback(board, totals, reason: str) -> MonthlyReview:
    ranked = board["ranked"]
    improving = [v for v in ranked if v["trend"]["onTimeTrend"] == sc.IMPROVING]
    declining = [v for v in ranked if v["trend"]["onTimeTrend"] == sc.DETERIORATING]
    weak = [v for v in ranked if v["scores"]["overall"] < 60]
    status = "NEEDS ATTENTION" if len(declining) >= 3 else "WATCH" if declining else "GOOD"
    note = lambda v, extra="": VendorNote(  # noqa: E731
        vendor=v["vendor"],
        note=f"{report.vendor_headline(v)} · {report.score_line(v)}{extra}")
    return MonthlyReview(
        overall_status=status,
        headline=(f"{totals['trips']} trips across {totals['vendors']} vendors, "
                  f"{report.pct(totals['onTimePct'])} on time, "
                  f"{report.money(totals['totalCost'])} spent."),
        best_performers=[note(v) for v in ranked[:3]],
        underperformers=[note(v) for v in (weak or ranked[-2:])],
        improving=[note(v, f" · on-time {v['trend']['onTimeChangePP']:+.1f}pp")
                   for v in improving[:3]],
        deteriorating=[note(v, f" · on-time {v['trend']['onTimeChangePP']:+.1f}pp")
                       for v in declining[:3]],
        cost_observations=[
            f"Programme spend {report.money(totals['totalCost'])} across "
            f"{totals['trips']} trips; cost data covers "
            f"{report.pct(totals['costCoveragePct'])} of them."],
        systemic_vs_isolated=(f"{len(declining)} of {len(ranked)} ranked vendors "
                              f"declined within the month."),
        management_actions=[f"Deterministic summary only ({reason})."],
    )


def _scorecard_table(board) -> str:
    rows = ["*VENDOR SCORECARD*  (service · reliability · cost value → overall)"]
    for v in board["ranked"][:8]:
        s = v["scores"]
        cost = "n/a" if s["costValue"] is None else f"{s['costValue']:>3.0f}"
        rows.append(f"`{v['rank']:>2}. {v['vendor'][:26]:<26}"
                    f"{s['service']:>5.0f} {s['reliability']:>5.0f} {cost:>5} "
                    f"→{s['overall']:>5.0f}`")
    return "\n".join(rows)


def format_message(window, review: MonthlyReview, board, totals, source) -> list[str]:
    icon = report.STATUS_ICON.get(review.overall_status, "🟡")
    head = [
        f"📈 *MONTHLY VENDOR REVIEW* · {window.label}",
        f"Overall status: {icon} {review.overall_status}",
        f"{totals['trips']} trips · {totals['vendors']} vendors · "
        f"on-time {report.pct(totals['onTimePct'])} · spend {report.money(totals['totalCost'])}",
        "",
        review.headline,
    ]
    blocks = [_scorecard_table(board)]
    named = lambda items: [f"*{n.vendor}* — {n.note}" for n in items]  # noqa: E731
    for title, items in (("🏆 Best performers", named(review.best_performers)),
                         ("⚠️ Underperformers", named(review.underperformers)),
                         ("🟢 Improving within the month", named(review.improving)),
                         ("🔴 Deteriorating within the month", named(review.deteriorating)),
                         ("💰 Cost & value", review.cost_observations),
                         ("🎯 Management actions", review.management_actions)):
        b = report.bullets(title, items)
        if b:
            blocks.append("\n".join(b))
    if review.systemic_vs_isolated:
        blocks.append(f"*Pattern:* {review.systemic_vs_isolated}")
    footer = "_" + " ".join(report.data_caveats(board, totals)) + f" Written by: {source}._"
    return slack.chunk("\n".join(head), blocks, footer)


def run(argv=None) -> int:
    p = argparse.ArgumentParser(description="Monthly vendor review → Slack")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--month", help="YYYY-MM; default is the last month in the data")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    if args.month:
        os.environ["VENDOR_MONTH"] = args.month
    cfg = Config.from_env()

    con, health = data_mod.connect(cfg.data_dir)
    try:
        window = periods.month_window(con, cfg)
        logger.info("trigger: monthly vendor review for %s", window.label)
        board = sc.build(con, window, periods.thirds(window), cfg)
        if not board["vendors"]:
            print(f"\nNo vendor activity in {window.label}\n")
            return 0
        totals = totals_of(board["vendors"])
        logger.info("trigger: %d vendors (%d ranked), %d trips",
                    totals["vendors"], len(board["ranked"]), totals["trips"])

        results, source = analysis._invoke(
            analysis._MONTHLY_SYSTEM,
            [analysis.monthly_context(window, board, totals)], MonthlyReview, cfg)
        review = results[0] or fallback(board, totals, "model unavailable")
        logger.info("trigger: narrative produced by %s", source)

        texts = format_message(window, review, board, totals, source)
        for t in texts:
            print("\n" + t + "\n")
        if args.json:
            print(json.dumps(review.model_dump(), indent=1))
        if args.dry_run or cfg.dry_run:
            logger.info("trigger: dry run, not posting to Slack")
            return 0
        sent = slack.send_all(texts)
        return 0 if all(r.delivered for r in sent) else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(run())
