"""The morning job. One command, end to end.

    python -m trigger.run_daily              # forecast, plan, post to Slack
    python -m trigger.run_daily --dry-run    # everything except the post
    python -m trigger.run_daily --date 2026-07-29

Slack is NOT re-implemented here: `signaldesk.delivery.slack_send` is the
repository's existing channel (it reads SLACK_WEBHOOK_URL, posts
{"text": ...}, and never raises), and this calls it unchanged.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from ..common import config as _cfg    # noqa: F401  -- puts service/ on sys.path
from ..common.config import ROOT
from .config import Config
from . import chain, format as fmt, stats as stats_mod
from signaldesk.delivery import slack_send

logger = logging.getLogger("trigger")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily transport shift plan → Slack")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the plan and print it, do not post to Slack")
    parser.add_argument("--date", help="plan for this date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true",
                        help="also print the computed statistics as JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")         # the repository's own .env

    if args.date:
        os.environ["TRIGGER_TARGET_DATE"] = args.date
    cfg = Config.from_env()

    logger.info("trigger: loading feeds from %s", cfg.data_dir)
    s = stats_mod.build(cfg)
    w = s["window"]
    logger.info("trigger: planning %s (%s), %d days of history, %d trips in window",
                w["targetDate"], w["targetWeekday"], w["historyDays"],
                s["reliability"]["trips"])

    plan, source = chain.plan(s, cfg)
    logger.info("trigger: plan produced by %s", source)

    text = fmt.slack_text(plan, s, source)
    print("\n" + text + "\n")
    if args.json:
        print(json.dumps(s, indent=1))

    if args.dry_run or cfg.dry_run:
        logger.info("trigger: dry run, not posting to Slack")
        return 0

    result = slack_send(text)
    logger.info("trigger: slack delivered=%s detail=%s", result.delivered, result.detail)
    return 0 if result.delivered else 1


if __name__ == "__main__":
    sys.exit(run())
