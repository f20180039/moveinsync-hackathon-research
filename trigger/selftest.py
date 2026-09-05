"""End-to-end check that needs no network and posts nothing.

    python -m trigger.selftest

Covers the five things that can silently break: the feeds load, the
statistics come out sane, the LangChain chain runs and its output parses
into a ShiftPlan, the deterministic fallback produces the same structure,
and the Slack payload is built correctly (captured, never sent).

The model is stubbed with a fake chat model, so this proves the CHAIN --
prompt, invocation, parsing, rendering -- not Sarvam's availability. A live
model call is what `python -m trigger.run_daily --dry-run` does.
"""
from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from .config import ROOT, Config
from . import chain, format as fmt, stats as stats_mod
from .schema import ShiftPlan

_STUB_PLAN = {
    "headline": "Wednesday runs heavy on the morning LOGIN leg.",
    "expected_demand": "48.2 trips and about 124 employees.",
    "peak_periods": ["13:00-14:00 carries 9.4% of the day's trips"],
    "shift_blocks": [{
        "window": "08:00-16:00", "band": "DAY", "direction": "LOGIN",
        "vehicles": 19, "drivers": 19, "expected_trips": 17.1,
        "expected_employees": 47.1, "note": "weakest on-time block",
    }],
    "capacity_risks": ["Average cab occupancy is 0.61."],
    "anomalies": ["EMPLOYEE_GEOFENCE_VIOLATION averages 0.57/day."],
    "eta_considerations": ["Historical on-time is 95.5%."],
    "recommended_actions": ["Roster 53 vehicles and 53 drivers."],
    "reasoning": "Seasonal-naive forecast over four matching weekdays.",
}


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = Config.from_env()
    results = []

    print(f"\n1. Load feeds from {cfg.data_dir}")
    s = stats_mod.build(cfg)
    results.append(_check("every feed loaded", len(s["feedHealth"]) == 5,
                          ", ".join(f"{k}={v['rows']}" for k, v in s["feedHealth"].items())))

    print("\n2. Statistics")
    f = s["forecast"]
    results.append(_check("trips in the history window",
                          s["reliability"]["trips"] > 0, str(s["reliability"]["trips"])))
    results.append(_check("forecast is a positive number",
                          f["forecastTrips"] > 0, str(f["forecastTrips"])))
    results.append(_check("peaks and shift blocks present",
                          bool(f["peakHours"]) and bool(f["byBand"]),
                          f"{len(f['peakHours'])} peaks, {len(f['byBand'])} blocks"))
    results.append(_check("plan target is after the data",
                          s["window"]["targetDate"] > s["window"]["dataLatestDate"]
                          or cfg.target_date is not None,
                          f"{s['window']['dataLatestDate']} → {s['window']['targetDate']}"))

    print("\n3. LangChain chain (stubbed model, no network)")
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    stub = FakeListChatModel(responses=[json.dumps(_STUB_PLAN)])
    plan, source = chain.plan(s, cfg, llm=stub)
    results.append(_check("chain ran and output parsed", source == "langchain", source))
    results.append(_check("parsed into a ShiftPlan",
                          isinstance(plan, ShiftPlan) and bool(plan.shift_blocks)))

    print("\n4. Deterministic fallback")
    fb = chain.fallback_plan(s, "selftest")
    results.append(_check("fallback builds the same structure",
                          isinstance(fb, ShiftPlan) and bool(fb.shift_blocks),
                          f"{len(fb.shift_blocks)} blocks"))
    results.append(_check("fallback used when the model is unreachable",
                          chain.plan(s, cfg, llm=_exploding())[1] == "fallback"))

    print("\n5. Slack payload (captured, not sent)")
    text = fmt.slack_text(fb, s, "fallback")
    captured = _capture_slack(text)
    results.append(_check("payload is {'text': ...}", captured.get("json", {}).keys() == {"text"}))
    results.append(_check("message within Slack's size limit",
                          0 < len(text) <= fmt.MAX_CHARS, f"{len(text)} chars"))
    results.append(_check("message names the day being planned",
                          s["window"]["targetDate"] in text))

    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if ok else 1


def _exploding():
    """A Runnable standing in for a model that cannot be reached at all --
    the 06:30 case this whole fallback exists for."""
    from langchain_core.runnables import RunnableLambda

    def boom(_input):
        raise ConnectionError("selftest: simulated outage")

    return RunnableLambda(boom)


def _capture_slack(text: str) -> dict:
    """Calls the REAL `signaldesk.delivery.slack_send` with httpx.post
    swapped out, so the payload it builds is verified without a post."""
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


if __name__ == "__main__":
    sys.exit(main())
