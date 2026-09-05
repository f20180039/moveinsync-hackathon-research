"""End-to-end check for the Team Manager agent. No network, posts nothing.

    python -m trigger.delay_management_TransportManager.selftest

Covers what can silently break: the rides load and are classified against a
simulated now, detection finds the right things and ignores corrupt ones,
each ride gets its OWN model call, a model figure never overwrites a computed
one, a single bad ride does not sink the batch, the Slack payload is built
correctly, and an unchanged escalation is suppressed on the next run.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from ..common.config import ROOT
from ..common.state import SeenStore
from . import delay_analyzer as analyzer, escalation_agent, format as fmt
from .config import Config
from .rides import StaticCsvRideSource
from .run_escalations import _fingerprint
from .schema import Escalation

DEMO_NOW = "2026-07-22 23:15"

_STUB = json.dumps({
    "ride_id": "REPLACED", "issue_type": "ETA deviation after a late start",
    "severity": "HIGH", "requires_attention": "Requires attention",
    "delay_minutes": 999,
    "likely_cause": "The driver started behind schedule and the arrival slipped with it.",
    "reasoning": "Start slip and arrival slip move together on this ride.",
    "recommended_action": "Call the driver and warn the site if the arrival cannot be held.",
})


def _check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def _exploding():
    from langchain_core.runnables import RunnableLambda

    def boom(_i):
        raise ConnectionError("selftest: simulated outage")
    return RunnableLambda(boom)


def _capture_slack(text: str) -> dict:
    """Calls the REAL `signaldesk.delivery.slack_send` with httpx.post swapped
    out, so the payload it builds is verified without a post."""
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


def main() -> int:
    load_dotenv(ROOT / ".env")
    import os
    os.environ["TEAM_NOW"] = DEMO_NOW
    cfg = Config.from_env()
    results = []

    print(f"\n1. Rides at a simulated now ({DEMO_NOW}), data {cfg.data_dir}")
    source = StaticCsvRideSource(cfg)
    rides = source.rides_in_scope()
    results.append(_check("rides in scope", len(rides) > 0, str(len(rides))))
    statuses = {r["status"] for r in rides}
    results.append(_check("rides carry a status", statuses <= {
        "IN_FLIGHT", "UPCOMING", "RECENTLY_COMPLETED"}, ", ".join(sorted(statuses))))
    results.append(_check("no ride is duplicated",
                          len({r["rideId"] for r in rides}) == len(rides)))
    not_started = [r for r in rides if r["status"] == "UPCOMING"]
    results.append(_check("an unstarted ride reports no actual start (no future leak)",
                          all(r["actualStartLocal"] is None for r in not_started),
                          f"{len(not_started)} upcoming"))

    print("\n2. Deterministic detection")
    found = analyzer.find_escalations(rides, cfg)
    results.append(_check("multiple rides flagged in one run", len(found) >= 3,
                          f"{len(found)} escalations"))
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    sev = [order[a["severityHint"]] for a in found]
    results.append(_check("worst first", sev == sorted(sev, reverse=True),
                          ", ".join(a["severityHint"] for a in found)))
    kinds = {c for a in found for c in a["factorCodes"]}
    results.append(_check("more than one kind of problem detected", len(kinds) >= 3,
                          ", ".join(sorted(kinds))))
    multi = [a for a in found if len(a["factors"]) >= 2]
    results.append(_check("a multi-factor ride is recognised", bool(multi),
                          f"{len(multi)} rides with 2+ factors"))

    print("\n3. Edge cases")
    blank = analyzer.analyze({"rideId": "EMPTY", "status": "UPCOMING"}, cfg)
    results.append(_check("a ride with almost no fields does not crash",
                          blank["factors"] == [] and blank["severityHint"] == "LOW"))
    results.append(_check("a missing planned arrival is reported, not guessed",
                          any("planned arrival" in d for d in blank["dataIssues"])))
    corrupt = analyzer.analyze({"rideId": "BAD", "status": "IN_FLIGHT",
                                "etaDeviationMin": 83481, "driverStartSlipMin": 83481,
                                "plannedArrivalLocal": "x"}, cfg)
    results.append(_check("an implausible timestamp is quarantined, not escalated",
                          corrupt["factors"] == [] and len(corrupt["dataIssues"]) == 2))
    results.append(_check("no escalations means no message",
                          fmt.messages([], "none", 0, cfg, source.health, DEMO_NOW) == []))

    print("\n4. LangChain — one independent call per ride")
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    stub = FakeListChatModel(responses=[_STUB] * len(found))
    escalations, src = escalation_agent.reason(found, cfg, llm=stub)
    results.append(_check("every flagged ride got its own escalation",
                          len(escalations) == len(found), f"{len(escalations)} in, {len(found)} out"))
    results.append(_check("reasoning came from the chain", src == "langchain", src))
    results.append(_check("each escalation is bound to its own ride",
                          [e.ride_id for e in escalations] == [a["rideId"] for a in found]))
    results.append(_check("a model-invented figure never reaches the manager",
                          all(e.delay_minutes == a["delayMinutes"]
                              for e, a in zip(escalations, found)),
                          "model said 999 on every ride"))
    floors = [a["severityHint"] for a in found]
    results.append(_check("severity never drops below the deterministic floor",
                          all(order[e.severity] >= order[f]
                              for e, f in zip(escalations, floors))))

    print("\n5. Model failure")
    fb, src = escalation_agent.reason(found, cfg, llm=_exploding())
    results.append(_check("an unreachable model still escalates every ride",
                          len(fb) == len(found) and src == "fallback"))
    results.append(_check("fallback escalations are the same shape",
                          all(isinstance(e, Escalation) and e.recommended_action for e in fb)))

    print("\n6. Slack payload (captured, not sent)")
    pairs = [(e, a, "NEW") for e, a in zip(escalations, found)]
    texts = fmt.messages(pairs, src, 0, cfg, source.health, DEMO_NOW)
    results.append(_check("message built", bool(texts), f"{len(texts)} message(s)"))
    from ..common.slack import MAX_CHARS
    results.append(_check("every part fits Slack's limit",
                          all(len(t) <= MAX_CHARS + 40 for t in texts),
                          ", ".join(str(len(t)) for t in texts)))
    joined = "\n".join(texts)
    results.append(_check("every ride appears in the message",
                          all(a["rideId"] in joined for a in found)))
    captured = _capture_slack(texts[0])
    results.append(_check("payload is {'text': ...}",
                          captured.get("json", {}).keys() == {"text"}))

    print("\n7. Spam control")
    with tempfile.TemporaryDirectory() as tmp:
        store = SeenStore(Path(tmp) / "seen.json")
        a = found[0]
        fp = _fingerprint(a)
        first = store.classify(a["rideId"], fp)
        store.record(a["rideId"], fp)
        second = store.classify(a["rideId"], fp)
        worse = dict(a, delayMinutes=(a["delayMinutes"] or 0) + 25)
        third = store.classify(a["rideId"], _fingerprint(worse))
        results.append(_check("first sighting is NEW", first == "NEW", first))
        results.append(_check("unchanged is REPEAT (suppressed)", second == "REPEAT", second))
        results.append(_check("materially worse is UPDATED (re-notified)",
                              third == "UPDATED", third))

    source.close()
    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
