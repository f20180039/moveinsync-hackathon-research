"""Render a ShiftPlan as the Slack message a Transport Manager actually reads.

Slack's incoming-webhook `text` field takes mrkdwn (`*bold*`, `_italic_`),
not Markdown -- `**bold**` renders as literal asterisks, which is why single
stars are used throughout.
"""
from __future__ import annotations

from .schema import ShiftPlan

MAX_CHARS = 3800        # Slack truncates a text block around 4k


def _bullets(title: str, items: list[str], limit: int = 4) -> list[str]:
    if not items:
        return []
    out = [f"*{title}*"]
    out += [f"• {i}" for i in items[:limit]]
    return out


def slack_text(plan: ShiftPlan, stats: dict, source: str) -> str:
    w = stats["window"]
    f = stats["forecast"]
    lines = [
        f"*Daily Shift Plan — {w['targetDate']} ({w['targetWeekday']})*",
        plan.headline,
        "",
        f"*Expected demand*  {f['forecastTrips']} trips · "
        f"~{f['forecastEmployees']} employees · "
        f"{f['vehiclesWithBuffer']} vehicles · {f['driversRequired']} drivers "
        f"(incl. {f['bufferPct']}% buffer)",
        plan.expected_demand,
    ]

    if plan.shift_blocks:
        lines += ["", "*Shift allocation*"]
        for b in plan.shift_blocks[:6]:
            note = f" — {b.note}" if b.note else ""
            lines.append(f"• `{b.window}` {b.band}/{b.direction}: "
                         f"{b.vehicles} cabs, {b.drivers} drivers · "
                         f"~{b.expected_trips} trips, ~{b.expected_employees} employees{note}")

    for title, items in (("Peak periods", plan.peak_periods),
                         ("Capacity risks", plan.capacity_risks),
                         ("ETA / operations", plan.eta_considerations),
                         ("Anomalies & risks", plan.anomalies),
                         ("Do this before the first shift", plan.recommended_actions)):
        block = _bullets(title, items)
        if block:
            lines += [""] + block

    if plan.reasoning:
        lines += ["", f"_Why:_ {plan.reasoning}"]

    confidence = ", ".join(f"{k} {v['confidence']}" for k, v in stats["feedHealth"].items())
    lines += [
        "",
        f"_Forecast: {f['basis']}; profile {f['profileBasis']}; "
        f"trend ×{f['trendFactor']}. Data through {w['dataLatestDate']}, "
        f"{w['historyDays']}-day window._",
        f"_Feed confidence: {confidence}. Written by: {source}._",
    ]

    # Task 19: PROVENANCE, last line, always present. Either this brief names
    # the sweep run it agrees with -- so a reader can open that run in the
    # console and match the figures -- or it says plainly that it could not
    # reconcile and may differ. A brief that quietly diverges from the console
    # is the failure this line exists to prevent.
    if w.get("provenance"):
        lines += ["", f"_{w['provenance']}_"]

    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 20].rstrip() + "\n_…truncated_"
    return text
