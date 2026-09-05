"""DAILY trigger — end-of-day vendor operations health.

    python -m trigger.vendor_strategy_Facilities_Head.daily.run --dry-run
    python -m trigger.vendor_strategy_Facilities_Head.daily.run --date 2026-07-31

Flow: one operating day's trips → deterministic per-vendor metrics and
scores → one LangChain call for interpretation → Slack.
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
from ..schema import DailyBrief, VendorConcern
from .. import scorecard as sc

logger = logging.getLogger("trigger")


def fallback(board, totals, reason: str) -> DailyBrief:
    """No model, no network — the same brief, written from the numbers."""
    ranked = board["ranked"]
    good = [v for v in ranked if v["scores"]["overall"] >= 75]
    weak = [v for v in ranked if v["scores"]["overall"] < 60 or
            (v["onTimePct"] is not None and v["onTimePct"] < 80)]
    status = ("NEEDS ATTENTION" if len(weak) >= 3 or totals.get("severeAlerts")
              else "WATCH" if weak else "GOOD")
    return DailyBrief(
        overall_status=status,
        headline=(f"{totals['trips']} trips across {totals['vendors']} vendors, "
                  f"{report.pct(totals['onTimePct'])} on time."),
        what_went_well=[f"{v['vendor']}: {report.vendor_headline(v)}" for v in good[:3]],
        what_went_poorly=[f"{v['vendor']}: {report.vendor_headline(v)}" for v in weak[:3]],
        anomalies=([f"{totals['severeAlerts']} severe alert(s) raised today."]
                   if totals.get("severeAlerts") else []),
        vendors_needing_attention=[
            VendorConcern(vendor=v["vendor"],
                          concern=f"on-time {report.pct(v['onTimePct'])}, "
                                  f"avg delay {v['avgDelayMin']} min",
                          action="Check today's delay pattern with the vendor.")
            for v in weak[:3]],
        recommended_actions=["Deterministic summary only (" + reason + ")."],
    )


def format_message(window, brief: DailyBrief, board, totals, source) -> list[str]:
    icon = report.STATUS_ICON.get(brief.overall_status, "🟡")
    head = [
        f"📊 *DAILY VENDOR PERFORMANCE* · {window.label}",
        f"Overall status: {icon} {brief.overall_status}",
        f"{totals['trips']} trips · {totals['vendors']} vendors · "
        f"on-time {report.pct(totals['onTimePct'])} · spend {report.money(totals['totalCost'])}",
        "",
        brief.headline,
    ]
    blocks = []
    top = board["ranked"][:3]
    if top:
        blocks.append("🏆 *TOP PERFORMERS*\n" + "\n".join(
            f"*{v['vendor']}*\n• {report.vendor_headline(v)}\n• {report.score_line(v)}"
            for v in top))
    if brief.vendors_needing_attention:
        lines = []
        for c in brief.vendors_needing_attention[:3]:
            v = next((x for x in board["vendors"] if x["vendor"] == c.vendor), None)
            lines.append(f"*{c.vendor}*"
                         + (f"\n• {report.vendor_headline(v)}" if v else "")
                         + f"\n• Concern: {c.concern}\n• Action: {c.action}")
        blocks.append("⚠️ *ATTENTION REQUIRED*\n" + "\n".join(lines))
    for title, items in (("✅ What went well", brief.what_went_well),
                         ("🔻 What went poorly", brief.what_went_poorly),
                         ("🔎 Anomalies", brief.anomalies),
                         ("🎯 Facilities Head actions", brief.recommended_actions)):
        b = report.bullets(title, items)
        if b:
            blocks.append("\n".join(b))
    caveats = report.data_caveats(board, totals)
    footer = ("_" + " ".join(caveats) + f" Written by: {source}._")
    return slack.chunk("\n".join(head), blocks, footer)


def run(argv=None) -> int:
    p = argparse.ArgumentParser(description="Daily vendor performance → Slack")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--date", help="YYYY-MM-DD; default is the last day in the data")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    if args.date:
        os.environ["VENDOR_DATE"] = args.date
    cfg = Config.from_env()

    con, health = data_mod.connect(cfg.data_dir)
    try:
        window = periods.day_window(con, cfg)
        logger.info("trigger: daily vendor review for %s %s", window.label,
                    f"({window.note})" if window.note else "")
        board = sc.build(con, window, [], cfg, min_trips=cfg.min_trips_daily)
        if not board["vendors"]:
            print(f"\nNo vendor activity on {window.label}\n")
            return 0
        totals = totals_of(board["vendors"])
        logger.info("trigger: %d vendors, %d trips", totals["vendors"], totals["trips"])

        results, source = analysis._invoke(
            analysis._DAILY_SYSTEM,
            [analysis.daily_context(window, board, totals)], DailyBrief, cfg)
        brief = results[0] or fallback(board, totals, "model unavailable")
        logger.info("trigger: narrative produced by %s", source)

        texts = format_message(window, brief, board, totals, source)
        for t in texts:
            print("\n" + t + "\n")
        if args.json:
            print(json.dumps(brief.model_dump(), indent=1))
        if args.dry_run or cfg.dry_run:
            logger.info("trigger: dry run, not posting to Slack")
            return 0
        results = slack.send_all(texts)
        return 0 if all(r.delivered for r in results) else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(run())
