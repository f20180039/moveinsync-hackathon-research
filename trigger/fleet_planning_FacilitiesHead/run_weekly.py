"""The weekly job. One command, end to end.

    python -m trigger.fleet_planning_FacilitiesHead.run_weekly
    python -m trigger.fleet_planning_FacilitiesHead.run_weekly --dry-run
    python -m trigger.fleet_planning_FacilitiesHead.run_weekly --json

Slack is NOT re-implemented here: `trigger.common.slack` wraps the
repository's own `signaldesk.delivery.slack_send`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from dotenv import load_dotenv

from ..common import config as _cfg    # noqa: F401  -- puts service/ on sys.path
from ..common import run_context, slack
from ..common.config import ROOT
from .config import Config
from . import chain, format as fmt, stats as stats_mod

logger = logging.getLogger("trigger")


def build(cfg=None, run=None) -> tuple[str, dict, str]:
    """(slack text, stats, source) -- the whole job without posting.

    Separated from `run` so the sweep-driven dispatcher (trigger.common.
    dispatch) and the selftest both build the exact message the CLI would,
    rather than a near-copy of it.
    """
    cfg = cfg or Config.from_env()
    if run is None:
        run = run_context.resolve("week")
    s = stats_mod.build(cfg, run)
    plan, source = chain.plan(s, cfg)
    return fmt.slack_text(plan, s, source), s, source


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Next week's predictive fleet plan → Slack")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the plan and print it, do not post to Slack")
    parser.add_argument("--json", action="store_true",
                        help="also print the computed table as JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")

    cfg = Config.from_env()
    ctx = run_context.resolve("week")
    logger.info("trigger: run context %s (%s)", ctx.source, ctx.run_id or ctx.detail)

    text, s, source = build(cfg, ctx)
    logger.info("trigger: week of %s, %d days projected, +%d/-%d vehicle-days, by %s",
                s["weekStart"], s["totals"]["daysProjected"],
                s["totals"]["vehiclesToAdd"], s["totals"]["vehiclesToRelease"], source)

    print("\n" + text + "\n")
    if args.json:
        print(json.dumps(s, indent=1))

    if args.dry_run or cfg.dry_run:
        logger.info("trigger: dry run, not posting to Slack")
        return 0

    result = slack.send(text)
    logger.info("trigger: slack delivered=%s detail=%s", result.delivered, result.detail)
    return 0 if result.delivered else 1


if __name__ == "__main__":
    sys.exit(run())
