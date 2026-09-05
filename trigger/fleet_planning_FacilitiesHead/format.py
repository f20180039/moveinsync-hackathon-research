"""Render a FleetPlan as the Slack message a Facilities Head reads.

Every FIGURE below comes from the `stats` dict, never from the plan object --
so the numbers a manager acts on are the ones Python computed, whether the
prose was written by the model or by the deterministic fallback. The plan
supplies sentences; stats supplies facts.

Slack's incoming-webhook `text` field takes mrkdwn (`*bold*`, `_italic_`), not
Markdown -- `**bold**` renders as literal asterisks.
"""
from __future__ import annotations

from .schema import FleetPlan

MAX_CHARS = 3800

_ARROW = {"ADD": "▲", "RELEASE": "▼", "HOLD": "=", "NO_PROJECTION": "?"}


def _bullets(title: str, items: list[str], limit: int = 4) -> list[str]:
    if not items:
        return []
    return [f"*{title}*"] + [f"• {i}" for i in items[:limit]]


def _day_line(d: dict) -> str:
    o = d["overall"]
    if o["withheld"] or o["projectedRiders"] is None:
        return (f"• `{d['date']}` {d['weekday'][:3]}: no projection "
                f"({o['basisDaysUsed']} of {o['basisDaysWanted']} basis days)")
    interval = ""
    if o["intervalLow"] is not None:
        interval = f" ({o['intervalLow']:.0f}–{o['intervalHigh']:.0f})"
    delta = ""
    if o["vehicleDelta"] is not None and o["vehicleDelta"] != 0:
        delta = f" {_ARROW[o['direction']]} {o['vehicleDelta']:+d} vs {o['ranDate']}"
    thin = f" · {o['basisDaysUsed']}/{o['basisDaysWanted']} basis days" \
        if o["basisDaysUsed"] < o["basisDaysWanted"] else ""
    return (f"• `{d['date']}` {d['weekday'][:3]}: ~{o['projectedRiders']:.0f} riders"
            f"{interval} → {o['vehiclesWithBuffer']} vehicles"
            f"{delta}{thin}")


def _band_line(r: dict) -> str:
    if r["vehicleDelta"] is None:
        return f"    {r['band']}: no projection"
    return (f"    {_ARROW[r['direction']]} {r['band']}: "
            f"{r['ranVehiclesWithBuffer']} → {r['vehiclesWithBuffer']} vehicles "
            f"({r['vehicleDelta']:+d}), ~{r['projectedRiders']:.0f} riders")


def slack_text(plan: FleetPlan, stats: dict, source: str) -> str:
    t = stats["totals"]
    lines = [
        f"*Fleet outlook — week of {stats['weekStart']} to {stats['weekEnd']}*",
        plan.headline,
        "",
        # BOTH SIDES on the headline row, always, even when one is zero: the
        # request was "don't fall short AND don't overbook", and reporting only
        # the side that happens to be non-zero this week teaches a reader that
        # the other side is not measured.
        f"*Vehicle change*  ▲ add {t['vehiclesToAdd']} · "
        f"▼ release {t['vehiclesToRelease']} "
        f"(vehicle-days, incl. {stats['bufferPct']}% standby buffer)",
        plan.demand_outlook,
        "",
        "*By day*",
    ]
    lines += [_day_line(d) for d in stats["days"]]

    # The bands that actually carry a call, deepest first -- a full grid of
    # 7 days x 4 bands is a wall, not a brief.
    calls = [r for d in stats["days"] for r in d["byBand"]
             if r["vehicleDelta"] not in (None, 0)]
    calls.sort(key=lambda r: -abs(r["vehicleDelta"]))
    if calls:
        lines += ["", "*Where the change is*"]
        seen_day = None
        for r in calls[:6]:
            if r["date"] != seen_day:
                lines.append(f"  `{r['date']}` {r['weekday'][:3]}")
                seen_day = r["date"]
            lines.append(_band_line(r))

    for title, items in (("Add vehicles", plan.add_where),
                         ("Release vehicles", plan.release_where),
                         ("Evidence to read this with", plan.evidence_caveats),
                         ("Before Monday", plan.recommended_actions)):
        block = _bullets(title, items)
        if block:
            lines += [""] + block

    if plan.reasoning:
        lines += ["", f"_Why:_ {plan.reasoning}"]

    # How much history every number above rests on. A manager preparing next
    # week has to be able to discount a thin figure, so this is a line in the
    # message and not a field in a log.
    evidence = (f"{t['daysProjected']} of {stats['daysAhead']} days projected")
    if t["daysWithheld"]:
        evidence += f", {t['daysWithheld']} withheld"
    if t["screenedBasisDays"]:
        evidence += (f", {len(t['screenedBasisDays'])} anomalous basis day(s) "
                     f"screened out ({', '.join(t['screenedBasisDays'][:3])}"
                     + ("…" if len(t["screenedBasisDays"]) > 3 else "") + ")")
    confidence = ", ".join(f"{k} {v['confidence']}" for k, v in stats["feedHealth"].items())
    lines += [
        "",
        f"_Method: {stats['method']} on {stats['metric']}; {evidence}. "
        f"Compared against the same weekday a week earlier. "
        f"A stated baseline, not a forecast._",
        f"_Feed confidence: {confidence}. Written by: {source}._",
    ]
    if stats.get("provenance"):
        lines += ["", f"_{stats['provenance']}_"]

    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - 20].rstrip() + "\n_…truncated_"
    return text
