"""Slack delivery for every agent -- a thin layer over the repository's OWN
channel.

`signaldesk.delivery.slack_send` is the existing implementation: it reads
SLACK_WEBHOOK_URL, posts {"text": ...}, and never raises. No second Slack
integration is created here; this only adds the one thing a multi-item
escalation message needs and shift planning did not -- splitting a message
that would exceed Slack's size limit into ordered parts.
"""
from __future__ import annotations

import logging

from . import config as _cfg          # noqa: F401  -- puts service/ on sys.path
from signaldesk.delivery import slack_send

logger = logging.getLogger("trigger")

MAX_CHARS = 3800        # Slack truncates a text block around 4k


def send(text: str):
    """One post through the existing channel."""
    return slack_send(text)


def chunk(header: str, items: list[str], footer: str = "") -> list[str]:
    """Pack `items` into as few messages as fit, never splitting an item.

    A wall of text is unreadable and a truncated escalation is worse than a
    second message, so this pages instead of cutting.
    """
    if not items:
        return [f"{header}\n{footer}".strip()]
    messages, current = [], header
    for item in items:
        candidate = f"{current}\n\n{item}"
        if len(candidate) + len(footer) > MAX_CHARS and current != header:
            messages.append(current)
            current = f"{header} (cont.)\n\n{item}"
        else:
            current = candidate
    messages.append(current)
    if footer:
        messages[-1] = f"{messages[-1]}\n\n{footer}"
    if len(messages) > 1:
        messages = [f"{m}\n_part {i + 1} of {len(messages)}_"
                    for i, m in enumerate(messages)]
    return messages


def send_all(messages: list[str]) -> list:
    results = []
    for m in messages:
        r = send(m)
        logger.info("trigger: slack delivered=%s detail=%s", r.delivered, r.detail)
        results.append(r)
    return results
