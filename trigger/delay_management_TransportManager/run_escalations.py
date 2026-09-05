"""The Team Manager escalation job.

    python -m trigger.delay_management_TransportManager.run_escalations               # detect → reason → Slack
    python -m trigger.delay_management_TransportManager.run_escalations --dry-run     # everything but the post
    python -m trigger.delay_management_TransportManager.run_escalations --now "2026-07-22 23:15"
    python -m trigger.delay_management_TransportManager.run_escalations --scan        # which moments have the most

Slack is NOT re-implemented: `signaldesk.delivery.slack_send` is the
repository's existing channel and `common.slack` only adds paging.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from ..common import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from ..common import slack
from ..common.config import ROOT
from ..common.state import SeenStore
from . import delay_analyzer as analyzer, escalation_agent, format as fmt
from .config import Config
from .rides import StaticCsvRideSource, _local

logger = logging.getLogger("trigger")


def _fingerprint(analysis) -> str:
    """What makes an escalation "the same one" as last run: same factors,
    same severity, same delay to the nearest 10 minutes. A ride that gets 15
    minutes worse re-notifies; a ride sitting at the same delay does not."""
    delay = analysis["delayMinutes"]
    bucket = "na" if delay is None else str(int(delay) // 10)
    return f"{'+'.join(sorted(analysis['factorCodes']))}|{analysis['severityHint']}|{bucket}"


def _scan(source, cfg, hours: int = 168) -> None:
    """Which simulated moments carry the most escalations -- for choosing a
    demo window honestly, instead of hunting by hand."""
    base_now = source.now_ms()
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    rows = []
    for slot in range(-hours * 4, 4 * 24):
        t = base_now + slot * 15 * 60_000
        source._now = t
        found = analyzer.find_escalations(source.rides_in_scope(), cfg)
        if found:
            worst = max(found, key=lambda a: order[a["severityHint"]])["severityHint"]
            rows.append((sum(order[a["severityHint"]] + 1 for a in found),
                         len(found), worst, t))
    rows.sort(reverse=True)
    source._now = base_now
    print("\nBusiest escalation moments in this dataset:\n")
    for score, n, worst, t in rows[:10]:
        print(f"  {_local(t, cfg.tz_offset_min)}   escalations={n:2d}  worst={worst}")
    print("\nRe-run with:  --now \"<moment>\"\n")


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ride escalations → Slack (Team Manager)")
    p.add_argument("--dry-run", action="store_true", help="build the message, do not post")
    p.add_argument("--now", help='simulated current time, "YYYY-MM-DD HH:MM" local')
    p.add_argument("--json", action="store_true", help="also print the escalations as JSON")
    p.add_argument("--scan", action="store_true",
                   help="report which simulated moments carry the most escalations")
    p.add_argument("--reset-state", action="store_true",
                   help="forget what was already notified")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    if args.now:
        os.environ["TEAM_NOW"] = args.now
    cfg = Config.from_env()

    logger.info("trigger: loading feeds from %s", cfg.data_dir)
    source = StaticCsvRideSource(cfg)
    try:
        if args.scan:
            _scan(source, cfg)
            return 0

        now_local = _local(source.now_ms(), cfg.tz_offset_min)
        rides = source.rides_in_scope()
        logger.info("trigger: %d rides in scope at %s", len(rides), now_local)

        analyses = analyzer.find_escalations(rides, cfg)
        logger.info("trigger: %d ride(s) flagged by deterministic checks", len(analyses))

        store = SeenStore(cfg.state_path)
        if args.reset_state:
            store.data = {}
        kept, suppressed = [], 0
        for a in analyses:
            state = store.classify(a["rideId"], _fingerprint(a))
            if state == "REPEAT" and not cfg.send_repeats:
                suppressed += 1
                continue
            kept.append((a, state))
        if suppressed:
            logger.info("trigger: %d unchanged escalation(s) suppressed", suppressed)

        if len(kept) > cfg.max_escalations:
            logger.info("trigger: capping %d escalations at %d (worst first)",
                        len(kept), cfg.max_escalations)
            kept = kept[:cfg.max_escalations]

        if not kept:
            logger.info("trigger: nothing to escalate")
            print(f"\nNo escalations at {now_local}"
                  + (f" ({suppressed} unchanged, suppressed)" if suppressed else "") + "\n")
            return 0

        escalations, llm_source = escalation_agent.reason([a for a, _s in kept], cfg)
        logger.info("trigger: reasoning produced by %s", llm_source)

        pairs = [(e, a, s) for e, (a, s) in zip(escalations, kept)]
        texts = fmt.messages(pairs, llm_source, suppressed, cfg, source.health, now_local)
        for t in texts:
            print("\n" + t + "\n")
        if args.json:
            print(json.dumps([e.model_dump() for e in escalations], indent=1))

        if args.dry_run or cfg.dry_run:
            logger.info("trigger: dry run, not posting to Slack and not recording state")
            return 0

        results = slack.send_all(texts)
        delivered = all(r.delivered for r in results)
        if delivered:
            for _e, a, _s in pairs:
                store.record(a["rideId"], _fingerprint(a),
                             {"severity": a["severityHint"]})
            store.save()
        return 0 if delivered else 1
    finally:
        source.close()


if __name__ == "__main__":
    sys.exit(run())
