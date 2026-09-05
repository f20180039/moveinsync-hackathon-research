"""The ACT step: routes a composed brief to Slack and/or email by the run's
worst tier for the given audience, and logs what was sent, to whom, and
which findings drove it.

No retry, no backoff: a channel failure is recorded, never propagated -- one
audience's Slack outage must not lose the email, and must never lose the
finding either (it stays in the log's finding_ids regardless of delivery).

Nothing here ever logs, returns, or embeds a webhook URL, an API key, or raw
exception text -- only the exception's class name. A Slack webhook URL is a
credential, and the dispatch result is rendered straight into the console.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from .compose import sarvam_brief
from .schemas import Audience, Tier

logger = logging.getLogger("signaldesk")


@dataclass(frozen=True)
class ChannelResult:
    channel: str
    delivered: bool
    detail: str


class Channel(Protocol):
    """What `slack_send` and `ses_send` both are: a zero-argument-beyond-the-
    message callable that never raises."""

    def __call__(self, *args, **kwargs) -> ChannelResult: ...


@dataclass(frozen=True)
class DispatchRecord:
    run_id: str
    audience: str
    tier: str
    channels: list[ChannelResult]
    finding_ids: list[str]
    sent_at_ms: int


# In-process only, like sweep.STORE -- audit-log persistence is out of scope.
DISPATCH_LOG: list[DispatchRecord] = []


def slack_send(text: str) -> ChannelResult:
    """POSTs {"text": text} to SLACK_WEBHOOK_URL. Never raises: a missing
    config or a failed request both come back as a ChannelResult."""
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return ChannelResult("slack", False, "not configured")
    try:
        r = httpx.post(url, json={"text": text}, timeout=10)
        r.raise_for_status()
        return ChannelResult("slack", True, f"status {r.status_code}")
    except Exception as exc:
        logger.warning("slack_send failed: %s", type(exc).__name__)
        return ChannelResult("slack", False, type(exc).__name__)


def ses_send(subject: str, body: str) -> ChannelResult:
    """Sends via boto3's SES client, from SES_FROM to SES_TO (comma-separated).
    Never raises: a missing config or a failed send both come back as a
    ChannelResult."""
    from_addr = os.environ.get("SES_FROM")
    to_addr = os.environ.get("SES_TO")
    if not from_addr or not to_addr:
        return ChannelResult("email", False, "not configured")
    try:
        import boto3
        client = boto3.client("ses", region_name=os.environ.get("AWS_REGION"))
        recipients = [a.strip() for a in to_addr.split(",") if a.strip()]
        client.send_email(
            Source=from_addr,
            Destination={"ToAddresses": recipients},
            Message={"Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}}})
        return ChannelResult("email", True, "sent")
    except Exception as exc:
        logger.warning("ses_send failed: %s", type(exc).__name__)
        return ChannelResult("email", False, type(exc).__name__)


def _worst_tier_for(run, audience: Audience) -> Tier:
    tiers = [f.tier for f in run.findings if audience in f.audiences]
    return max(tiers) if tiers else Tier.PASS


def _audiences_in(run) -> list[Audience]:
    """Every audience actually addressed by this run's findings, in the
    Audience enum's own declaration order (stable across runs -- see
    api.finding_to_json's identical concern with frozenset iteration order)."""
    present = {a for f in run.findings for a in f.audiences}
    return [a for a in Audience if a in present]


def dispatch(run, audiences: list[Audience] | None = None) -> list[DispatchRecord]:
    """Composes one brief per audience (present in the run, or given
    explicitly), routes it by that audience's worst tier, and appends a
    DispatchRecord to DISPATCH_LOG for every audience considered -- including
    PASS, which routes to no channel but is still logged as skipped."""
    targets = audiences if audiences is not None else _audiences_in(run)
    records: list[DispatchRecord] = []

    for audience in targets:
        tier = _worst_tier_for(run, audience)
        finding_ids = [f.id for f in run.findings if audience in f.audiences]
        channels: list[ChannelResult] = []

        if tier in (Tier.BREACH, Tier.CONCERN):
            brief = sarvam_brief(run, audience)
            subject = (f"Signal Desk — {audience.value.replace('_', ' ').title()} "
                      f"brief — {run.window.label}")
            channels.append(slack_send(brief))
            channels.append(ses_send(subject, brief))
        elif tier is Tier.WATCH:
            brief = sarvam_brief(run, audience)
            channels.append(slack_send(brief))
        else:
            logger.info("dispatch: skipped audience=%s tier=PASS run_id=%s",
                       audience.value, run.run_id)

        record = DispatchRecord(run.run_id, audience.value, tier.name, channels,
                               finding_ids, int(time.time() * 1000))
        DISPATCH_LOG.append(record)
        records.append(record)

    return records
