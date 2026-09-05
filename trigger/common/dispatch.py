"""Task 19 (3) -- fire the trigger agents when a sweep finishes, instead of
only when someone runs them by hand.

THE GUARDRAILS, all of them load-bearing, none of them optional:

1. OPT-IN, DEFAULT OFF. `TRIGGER_ON_SWEEP` must be set to a truthy value.
   Nothing may start posting to Slack because somebody ran a sweep -- a judge,
   a test, or a local demo must not spam a real channel. `enabled()` is the
   single gate and it is checked before anything else happens.

2. NO TEST EVER POSTS. Two independent reasons, so removing either one still
   leaves the other: the env var is off by default (1), and `dry_run` short-
   circuits before delivery. trigger/common/selftest_dispatch.py asserts that
   a dispatch under test conditions performs zero sends.

3. NEVER BLOCKS OR SLOWS THE SWEEP. `fire_async` starts a daemon thread and
   returns immediately -- the same pattern the sweep endpoint itself uses
   (commit fd00769: the job outlives the proxy, so it does not run inline).

4. A FAILED DELIVERY MUST NOT BREAK THE SWEEP. Every path here is wrapped;
   the worst outcome is a logged warning and no Slack message.

5. SPAM CONTROL IS LOAD-BEARING NOW, not optional. Firing on every sweep means
   a service restart, a replay, or a judge pressing the button re-runs this.
   The existing SeenStore (NEW / UPDATED / REPEAT) is what stops an unchanged
   situation being re-posted, and -- exactly as the escalation agent does it --
   STATE IS WRITTEN ONLY AFTER SLACK ACCEPTS, so a failed post is retried next
   time rather than being silently marked as sent.

The fingerprint is the agent's own decision content, not the run id: a new
sweep over unchanged data produces a new run id but the SAME fleet plan, and
re-posting that is precisely the spam this guards against. A materially
different plan is UPDATED and does post.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

from .config import STATE_DIR, env_bool
from .state import NEW, REPEAT, UPDATED, SeenStore

logger = logging.getLogger("trigger")

STATE_FILE = STATE_DIR / "dispatch.json"

# The agents this fires, by name. Deliberately a short explicit list rather
# than discovery: what posts to a company Slack channel should be something a
# human wrote down.
FLEET = "fleet_planning_FacilitiesHead"
DEFAULT_AGENTS = (FLEET,)


def enabled() -> bool:
    """Guardrail 1. Off unless explicitly switched on."""
    return env_bool("TRIGGER_ON_SWEEP", False)


def selected_agents() -> tuple[str, ...]:
    raw = os.environ.get("TRIGGER_ON_SWEEP_AGENTS", "").strip()
    if not raw:
        return DEFAULT_AGENTS
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    return names or DEFAULT_AGENTS


def _fingerprint(stats: dict) -> str:
    """What makes this plan DIFFERENT from the last one posted.

    The run id is deliberately NOT in it: a sweep over unchanged data mints a
    new run id and the same plan, and re-posting that is the spam this exists
    to stop. The week being planned and the per-band vehicle calls are the
    decision; everything else is presentation.
    """
    material = {
        "weekStart": stats.get("weekStart"),
        "calls": sorted(
            (r["date"], r["band"], r["direction"], r["vehicleDelta"])
            for d in stats.get("days", []) for r in d.get("byBand", [])
        ),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _build_fleet(run):
    from ..fleet_planning_FacilitiesHead.run_weekly import build
    return build(run=run)


_BUILDERS = {FLEET: _build_fleet}


def dispatch(run=None, agents=None, sender=None, store=None,
             dry_run: bool | None = None) -> list[dict]:
    """Build and (maybe) post each selected agent's message.

    Returns one result dict per agent, so a caller -- or a test -- can see
    exactly what happened without reading a log. `sender` and `store` are
    injectable for the selftest; production passes neither.

    Never raises. An agent that blows up is reported as an error and the next
    one still runs: one broken agent must not silence the others, and neither
    may take the sweep down with it.
    """
    if not enabled():
        return [{"agent": a, "action": "disabled",
                 "detail": "TRIGGER_ON_SWEEP is not set"} for a in (agents or ())]

    from . import slack as slack_mod
    send = sender or slack_mod.send
    seen = store if store is not None else SeenStore(STATE_FILE)
    results = []

    for name in (agents or selected_agents()):
        builder = _BUILDERS.get(name)
        if builder is None:
            results.append({"agent": name, "action": "unknown",
                            "detail": "no such agent"})
            continue
        try:
            text, stats, source = builder(run)
        except Exception as exc:                       # guardrail 4
            logger.warning("trigger: %s failed to build (%s)", name, type(exc).__name__,
                           exc_info=True)
            results.append({"agent": name, "action": "error",
                            "detail": type(exc).__name__})
            continue

        fp = _fingerprint(stats)
        verdict = seen.classify(name, fp)
        if verdict == REPEAT:
            # Guardrail 5: an unchanged situation is not news. A sweep on
            # every restart must not re-post the same plan.
            results.append({"agent": name, "action": "suppressed",
                            "detail": REPEAT, "fingerprint": fp})
            continue

        is_dry = dry_run if dry_run is not None else env_bool("TRIGGER_DRY_RUN", False)
        if is_dry:
            # Guardrail 2's second, independent line of defence.
            results.append({"agent": name, "action": "dry_run",
                            "detail": verdict, "fingerprint": fp,
                            "chars": len(text)})
            continue

        try:
            result = send(text)
            delivered = bool(getattr(result, "delivered", False))
        except Exception as exc:                       # guardrail 4
            logger.warning("trigger: %s slack send raised (%s)", name, type(exc).__name__)
            results.append({"agent": name, "action": "error",
                            "detail": type(exc).__name__})
            continue

        if delivered:
            # State is written ONLY after Slack accepts -- a failed post must
            # be retried next sweep, not silently recorded as sent.
            seen.record(name, fp, {"source": source,
                                   "runId": (run.run_id if run is not None else None)})
            seen.save()
            results.append({"agent": name, "action": "posted", "detail": verdict,
                            "fingerprint": fp})
        else:
            results.append({"agent": name, "action": "not_delivered",
                            "detail": getattr(result, "detail", ""),
                            "fingerprint": fp})

    for r in results:
        logger.info("trigger: dispatch %s -> %s (%s)",
                    r["agent"], r["action"], r.get("detail", ""))
    return results


def fire_async(run=None) -> threading.Thread | None:
    """Guardrail 3: start the dispatch on a daemon thread and return at once.

    The sweep endpoint already returns immediately and runs the sweep in the
    background; this must not undo that by making sweep completion wait on a
    Slack round trip. Returns None when dispatch is switched off, so a caller
    can tell "not started" from "started".
    """
    if not enabled():
        return None
    t = threading.Thread(target=_safe_dispatch, args=(run,), daemon=True,
                         name="trigger-dispatch")
    t.start()
    return t


def _safe_dispatch(run) -> None:
    try:
        dispatch(run)
    except Exception:                                  # guardrail 4, outermost
        logger.warning("trigger: dispatch failed", exc_info=True)
