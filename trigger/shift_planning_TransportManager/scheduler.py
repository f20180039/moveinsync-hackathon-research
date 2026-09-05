"""Fire `run_daily` once every morning at TRIGGER_RUN_AT.

The repository has no scheduling framework to reuse -- the existing sweep
runs on FastAPI's startup event and there is no cron, Celery or APScheduler
anywhere in the tree -- so this adds none either. It is a stdlib sleep loop,
for when the job should run inside an existing process or container.

Where a real scheduler exists, prefer it and call the module directly:

    30 6 * * *  cd /path/to/repo && .venv/bin/python -m trigger.run_daily

Both paths run exactly the same code.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from ..common.config import ROOT
from .config import Config
from .run_daily import run

logger = logging.getLogger("trigger")


def _seconds_until(run_at: str, tz_offset_min: int) -> float:
    tz = timezone(timedelta(minutes=tz_offset_min))
    hh, mm = (int(p) for p in run_at.split(":", 1))
    now = datetime.now(tz)
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    cfg = Config.from_env()
    logger.info("trigger: scheduler up, firing daily at %s (UTC%+d min)",
                cfg.run_at, cfg.tz_offset_min)
    while True:
        wait = _seconds_until(cfg.run_at, cfg.tz_offset_min)
        logger.info("trigger: next run in %.1f h", wait / 3600)
        time.sleep(wait)
        try:
            run([])
        except Exception as exc:      # a bad morning must not kill the loop
            logger.exception("trigger: run failed (%s)", type(exc).__name__)
        time.sleep(60)                # never fire twice inside the same minute


if __name__ == "__main__":
    main()
