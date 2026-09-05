"""delivery.py: routes a composed brief by the run's worst tier for an
audience, and logs what was sent, to whom, and from which findings -- without
ever leaking a webhook URL, a key, or raw exception text.

Tests stub httpx.post and a fake SES client -- no network in this suite. The
autouse fixture below also clears SARVAM_API_KEY, so dispatch()'s internal
sarvam_brief() call takes the template path and makes no model call either,
even though a real key may be loaded from ../.env by conftest.
"""
from __future__ import annotations

import logging

import pytest

from signaldesk import delivery
from signaldesk.delivery import dispatch
from signaldesk.schemas import (Audience, Cause, Dimension, FeedHealth, Finding,
                                Reference, ReferenceKind, Slice, Tier, Window,
                                finding_id)
from signaldesk.sweep import SweepRun

WINDOW = Window(1_000_000_000_000, 1_000_604_800_000)
FAKE_WEBHOOK = "https://hooks.example.test/services/FAKE/FAKE/fake"


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "")


def _finding(metric_id="vendor_ota", tier=Tier.BREACH, cause=Cause.PEER_LAGGARD,
            audiences=frozenset({Audience.TRANSPORT_MANAGER})):
    slc = Slice(Dimension.VENDOR, "Aarav Petrov Travel")
    refs = (Reference(ReferenceKind.TREND, 55.0, "4-week average"),
           Reference(ReferenceKind.PEER, 60.0, "peer median"))
    gap = 0.0 if tier is Tier.PASS else 25.0
    return Finding(finding_id(metric_id, slc, WINDOW), metric_id, slc, WINDOW, 61.4,
                  refs, tier, cause, gap, 0.95, audiences,
                  "SELECT 1 -- evidence only")


def _run(findings, feed_health=None):
    feed_health = feed_health if feed_health is not None else {
        "trips": FeedHealth("trips", 10_000, 100, 10, 5, 0.98),
    }
    return SweepRun("run-test", WINDOW, tuple(findings), feed_health, WINDOW.end_ms)


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSESClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_email(self, **kwargs):
        if self.fail:
            raise RuntimeError("ses unavailable")
        self.sent.append(kwargs)
        return {"MessageId": "fake-id"}


def _configure_channels(monkeypatch, slack_ok=True, ses_ok=True):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", FAKE_WEBHOOK)
    monkeypatch.setenv("SES_FROM", "signaldesk@example.test")
    monkeypatch.setenv("SES_TO", "manager@example.test")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")

    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json, timeout))
        return FakeResponse(200 if slack_ok else 500)

    monkeypatch.setattr(delivery.httpx, "post", fake_post)

    client = FakeSESClient(fail=not ses_ok)
    monkeypatch.setattr("boto3.client", lambda *a, **k: client)
    return calls, client


# ---------------------------------------------------------------------------

def test_breach_and_concern_go_to_both_channels(monkeypatch):
    calls, ses_client = _configure_channels(monkeypatch)
    for tier in (Tier.BREACH, Tier.CONCERN):
        run = _run([_finding(tier=tier)])
        records = dispatch(run, [Audience.TRANSPORT_MANAGER])
        channels = {c.channel for c in records[0].channels}
        assert channels == {"slack", "email"}
        assert all(c.delivered for c in records[0].channels)
    assert len(calls) == 2
    assert len(ses_client.sent) == 2


def test_watch_goes_to_slack_only(monkeypatch):
    calls, ses_client = _configure_channels(monkeypatch)
    run = _run([_finding(tier=Tier.WATCH, cause=Cause.LOW_CONFIDENCE)])
    records = dispatch(run, [Audience.TRANSPORT_MANAGER])
    channels = [c.channel for c in records[0].channels]
    assert channels == ["slack"]
    assert len(calls) == 1
    assert len(ses_client.sent) == 0


def test_pass_goes_nowhere(monkeypatch):
    calls, ses_client = _configure_channels(monkeypatch)
    run = _run([_finding(tier=Tier.PASS, cause=Cause.ON_REFERENCE)])
    records = dispatch(run, [Audience.TRANSPORT_MANAGER])
    assert records[0].channels == []
    assert len(calls) == 0
    assert len(ses_client.sent) == 0
    # the finding is still on record even though nothing was sent
    assert records[0].finding_ids


def test_a_channel_failure_is_recorded_and_does_not_lose_the_finding(monkeypatch):
    _configure_channels(monkeypatch, slack_ok=False, ses_ok=True)
    run = _run([_finding(tier=Tier.BREACH)])
    records = dispatch(run, [Audience.TRANSPORT_MANAGER])
    by_channel = {c.channel: c for c in records[0].channels}
    assert by_channel["slack"].delivered is False
    assert by_channel["email"].delivered is True
    # the failed channel does not erase which findings this dispatch was about
    assert records[0].finding_ids == [f.id for f in run.findings]


def test_every_dispatch_records_what_was_sent_to_whom_and_from_which_findings(monkeypatch):
    _configure_channels(monkeypatch)
    f1 = _finding(tier=Tier.BREACH)
    run = _run([f1])
    before = len(delivery.DISPATCH_LOG)
    records = dispatch(run, [Audience.TRANSPORT_MANAGER])
    assert len(delivery.DISPATCH_LOG) == before + 1
    logged = delivery.DISPATCH_LOG[-1]
    assert logged is records[0]
    assert logged.run_id == run.run_id
    assert logged.audience == Audience.TRANSPORT_MANAGER.value
    assert logged.tier == Tier.BREACH.name
    assert logged.finding_ids == [f1.id]
    assert {c.channel for c in logged.channels} == {"slack", "email"}


def test_the_webhook_url_never_appears_in_a_log_line_or_a_result(monkeypatch, caplog):
    _configure_channels(monkeypatch, slack_ok=False, ses_ok=False)
    caplog.set_level(logging.WARNING)
    run = _run([_finding(tier=Tier.BREACH)])
    records = dispatch(run, [Audience.TRANSPORT_MANAGER])

    for c in records[0].channels:
        assert FAKE_WEBHOOK not in c.detail
        assert "hooks.example.test" not in c.detail

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert FAKE_WEBHOOK not in log_text
    assert "hooks.example.test" not in log_text
