"""Render escalations as the Slack message a Team Manager can act on.

Option A from the brief: ONE message carrying every escalation in this run,
ranked worst first, each ride its own readable block -- so a manager sees the
whole operational picture in one notification rather than four pings. If the
run produces more than fits, `common.slack.chunk` pages it into ordered
parts rather than truncating an escalation.

Slack's incoming-webhook `text` takes mrkdwn (`*bold*`), not Markdown.
"""
from __future__ import annotations

from .schema import Escalation

_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}


def _ride_line(ride: dict) -> str:
    bits = [ride.get("status", "").replace("_", " ").lower()]
    if ride.get("direction"):
        bits.append(ride["direction"])
    if ride.get("site"):
        bits.append(ride["site"])
    if ride.get("vendor"):
        bits.append(ride["vendor"])
    return " · ".join(b for b in bits if b)


def _timing_line(ride: dict) -> str | None:
    planned = ride.get("plannedArrivalLocal")
    expected = ride.get("expectedArrivalLocal")
    if not planned or not expected:
        return None
    basis = ride.get("etaBasis")
    tag = {"projected": "projected from actual start",
           "observed": "actual arrival",
           "planned": "as planned"}.get(basis, basis or "")
    line = f"Planned arrival {planned} → {expected}"
    if tag:
        line += f" ({tag})"
    if ride.get("actualStartLocal") and ride.get("scheduledStartLocal"):
        line += (f" · driver started {ride['actualStartLocal']} "
                 f"vs {ride['scheduledStartLocal']} scheduled")
    return line


def block(index: int, esc: Escalation, analysis: dict, state: str) -> str:
    ride = analysis["ride"]
    icon = _ICON.get(esc.severity, "⚪")
    delay = f" · {esc.delay_minutes} min" if esc.delay_minutes is not None else ""
    flag = "" if state == "NEW" else f" · _{state.lower()}_"
    lines = [
        f"{icon} *{index}. Ride {esc.ride_id} — {esc.severity}* · {esc.requires_attention}{flag}",
        f"{esc.issue_type}{delay} · {_ride_line(ride)}",
    ]
    timing = _timing_line(ride)
    if timing:
        lines.append(timing)
    lines.append(f"*Cause:* {esc.likely_cause}")
    lines.append(f"*Action:* {esc.recommended_action}")
    if esc.reasoning:
        lines.append(f"_Why:_ {esc.reasoning}")
    if analysis["dataIssues"]:
        lines.append(f"_Data caveat:_ {'; '.join(analysis['dataIssues'])}")
    return "\n".join(lines)


def header(count: int, now_local: str) -> str:
    what = "ride escalation" if count == 1 else "ride escalations"
    return f"🚨 *Team Manager — {count} {what}* · as at {now_local}"


def footer(escalations, source: str, suppressed: int, cfg, health: dict) -> str:
    by_sev: dict[str, int] = {}
    for e in escalations:
        by_sev[e.severity] = by_sev.get(e.severity, 0) + 1
    mix = ", ".join(f"{v}×{k}" for k, v in sorted(by_sev.items()))
    parts = [f"_{mix}_" if mix else ""]
    if suppressed:
        parts.append(f"_{suppressed} unchanged escalation(s) suppressed since the last run._")
    confidence = ", ".join(f"{k} {v['confidence']}" for k, v in health.items())
    parts.append(f"_Reasoning: {source}. Feed confidence: {confidence}._")
    parts.append("_Static dataset: \"now\" is a simulated moment inside the data, "
                 "not wall-clock time._")
    return "\n".join(p for p in parts if p)


def messages(pairs, source: str, suppressed: int, cfg, health: dict,
             now_local: str) -> list[str]:
    """`pairs` is [(Escalation, analysis, state), ...] worst first."""
    from ..common.slack import chunk
    if not pairs:
        return []
    blocks = [block(i + 1, e, a, s) for i, (e, a, s) in enumerate(pairs)]
    return chunk(header(len(pairs), now_local), blocks,
                 footer([e for e, _a, _s in pairs], source, suppressed, cfg, health))
