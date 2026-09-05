"""The SENSE step. Iterates every (metric x slice) pair, evaluates the rules, and
stores findings. NO PROMPT IS INVOLVED.

This is the step that satisfies "agentic -- senses, reasons and acts", and it must
be visibly automatic in the demo: the manual trigger exists so a judge can watch
it fire, not because the loop needs asking.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace

from . import decompose, registry, verdict
from .schemas import FeedHealth, Finding, Slice, Tier, Window

logger = logging.getLogger("signaldesk")

# Fix wave 2: the console's Overview cards each used to fetch /decompose on
# mount (5 requests per load) -- computing the top-2 contributors here,
# once per sweep, for every finding worth showing them on, moves that cost
# to the sweep and off every card render. Capped at the top 25 (by rank) of
# the findings that clear the tier floor, not every one of them -- a
# real-dataset audience can carry 150+ CONCERN-or-worse findings, and this
# runs once per sweep, not on demand.
OWNS_MIN_TIER = Tier.CONCERN
MAX_OWNS_COMPUTATIONS = 25


def _owns_for(con, f: Finding) -> tuple[tuple[str, float, int], ...]:
    dim = decompose.dimension_for(f)
    try:
        rows = decompose.decompose(con, f, dim)
    except Exception:
        logger.warning("sweep: decompose(%s) failed for finding %s while attaching owns",
                       dim.name, f.id, exc_info=True)
        return ()
    named = [r for r in rows if r["value"] != decompose.OTHER][:2]
    return tuple((r["value"], r["points_of_gap"], r["n"]) for r in named)


def _attach_owns(con, ranked: list[Finding]) -> list[Finding]:
    out = []
    computed = 0
    for f in ranked:
        if f.tier >= OWNS_MIN_TIER and computed < MAX_OWNS_COMPUTATIONS:
            owns = _owns_for(con, f)
            computed += 1
            if owns:
                f = replace(f, owns=owns)
        out.append(f)
    return out


@dataclass
class Clock:
    """A fixed simulated clock. The demo drives this, not wall-clock time, so the
    same dataset always produces the same findings."""
    now_ms: int

    def millis(self) -> int:
        return self.now_ms


@dataclass
class ReplayClock(Clock):
    """Advances the simulated date at `speed` x real time, so a 90-day dataset
    replays in minutes and alerts fire LIVE on stage.

    This is what turns "the loop starts without a prompt" from a claim a judge
    has to take on trust into something they watch happen.
    """
    speed: float = 60.0 * 60.0 * 24.0     # one simulated day per real second
    started_at: float = field(default_factory=time.monotonic)
    running: bool = False

    def millis(self) -> int:
        if not self.running:
            return self.now_ms
        elapsed = time.monotonic() - self.started_at
        return int(self.now_ms + elapsed * self.speed * 1000)

    def start(self):
        self.started_at = time.monotonic()
        self.running = True

    def stop(self):
        self.now_ms = self.millis()
        self.running = False


@dataclass(frozen=True)
class SweepRun:
    run_id: str
    window: Window
    findings: tuple[Finding, ...]
    feed_health: dict[str, FeedHealth]
    swept_at_ms: int
    # Window parameter: "week" (7 days, the default -- startup() never
    # overrides this) or "month" (28 days -- api.post_sweep's only other
    # value). Purely descriptive: window.label/window's own length already
    # carry the real span; this is what the console shows as the toggle
    # state and what a re-opened run reports about itself.
    window_kind: str = "week"


def sweep(con, clock: Clock, health: dict[str, FeedHealth],
          metric_ids=registry.TIER_1_METRICS, window_days: int = 7,
          window_kind: str = "week") -> SweepRun:
    # Controller ruling (task-5): clear the memoisation cache FIRST. The
    # registry keys evaluate()/coverage() by (id(con), metric, slice, window) --
    # safe across sweeps for a fixed connection ONLY because every sweep starts
    # from a clean cache, never a stale one from a previous run against the
    # same connection.
    registry.clear_cache()

    now = clock.millis()
    window = Window(now - window_days * 86_400_000, now)

    found: list[Finding] = []
    for metric in registry.active(metric_ids):
        feed_conf = health[metric.source].confidence if metric.source in health else 0.0
        f = verdict.evaluate_finding(con, metric, Slice.all(), window, feed_conf)
        if f:
            found.append(f)
        # Fix-wave I3: metric.dims, not every Dimension -- ota/otd exclude
        # DIRECTION (each already hardcodes its own direction filter) and
        # vendor_ota is VENDOR-only. Iterating a metric's own dims, rather
        # than every dimension unconditionally, is what stops a metric from
        # producing a duplicate or mislabelled finding.
        for dim in metric.dims:
            for value in registry.distinct_values(con, dim, window):
                f = verdict.evaluate_finding(con, metric, Slice(dim, value), window, feed_conf)
                if f:
                    found.append(f)

    ranked = verdict.rank(found)
    ranked = _attach_owns(con, ranked)
    # Derived from the simulated clock and the finding count, not a uuid, so a
    # rerun of the demo produces the same id and a bookmarked URL still resolves.
    run_id = f"run-{now}-{len(ranked):x}"
    return SweepRun(run_id, window, tuple(ranked), health, now, window_kind)


class Store:
    """In-process only. Audit-log persistence is explicitly out of scope; this
    exists so the console and the interrogator can re-read a run."""

    def __init__(self):
        self._runs: dict[str, SweepRun] = {}
        self._findings: dict[str, Finding] = {}
        self._latest: str | None = None
        self._lock = threading.Lock()

    def put(self, run: SweepRun):
        with self._lock:
            self._runs[run.run_id] = run
            self._findings.update({f.id: f for f in run.findings})
            self._latest = run.run_id

    def get(self, run_id: str) -> SweepRun | None:
        return self._runs.get(self._latest if run_id == "latest" else run_id)

    def finding(self, finding_id: str) -> Finding | None:
        return self._findings.get(finding_id)


STORE = Store()
