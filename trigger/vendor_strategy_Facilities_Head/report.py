"""Shared Slack rendering. Every figure printed here comes from `metrics.py`
or `scorecard.py` -- never from the model."""
from __future__ import annotations

RULE = "━━━━━━━━━━━━━━━━━━━━━━"
THIN = "──────────────────────"

STATUS_ICON = {"GOOD": "🟢", "WATCH": "🟡", "NEEDS ATTENTION": "🔴"}
TREND_ICON = {"IMPROVING": "🟢 improving", "STABLE": "🟢 stable",
              "VOLATILE": "🟡 volatile", "DETERIORATING": "🔴 deteriorating",
              "INSUFFICIENT_DATA": "⚪ not enough data"}
REC_ICON = {"CONTINUE — INCREASE ALLOCATION": "⬆️", "CONTINUE — PREFERRED": "⭐",
            "CONTINUE": "✅", "CONTINUE — PERFORMANCE MONITORING": "👁",
            "REVIEW CONTRACT": "📄", "REDUCE ALLOCATION": "⬇️",
            "CONSIDER REPLACEMENT": "⛔"}


def money(v) -> str:
    if v is None:
        return "n/a"
    return f"₹{v:,.0f}"


def pct(v) -> str:
    return "n/a" if v is None else f"{v}%"


def score_line(v: dict) -> str:
    s = v["scores"]
    cost = "n/a" if s["costValue"] is None else f"{s['costValue']:.0f}"
    return (f"service {s['service']:.0f} · reliability {s['reliability']:.0f} · "
            f"cost value {cost} → *{s['overall']:.0f}/100*")


def vendor_headline(v: dict) -> str:
    return (f"{v['trips']} trips · on-time {pct(v['onTimePct'])} · "
            f"SLA {pct(v['slaAdherencePct'])} · "
            f"cost/on-time trip {money(v['costPerOnTimeTrip'])}")


def bullets(title: str, items, limit: int = 4) -> list[str]:
    items = [i for i in (items or []) if i]
    if not items:
        return []
    return [f"*{title}*"] + [f"• {i}" for i in items[:limit]]


def data_caveats(board: dict, totals: dict) -> list[str]:
    out = []
    if totals.get("costCoveragePct") is not None and totals["costCoveragePct"] < 100:
        out.append(f"Cost data covers {totals['costCoveragePct']}% of trips; "
                   f"value-for-money is assessed on that subset.")
    no_cost = [v["vendor"] for v in board["vendors"] if v["costPerOnTimeTrip"] is None]
    if no_cost:
        out.append(f"No cost data for {', '.join(no_cost[:3])}"
                   + (f" and {len(no_cost) - 3} more" if len(no_cost) > 3 else "")
                   + " — value for money cannot be concluded on price for them.")
    if board["unranked"]:
        out.append(f"{len(board['unranked'])} vendor(s) below the ranking floor are "
                   f"reported but not ranked.")
    out.append("The dataset carries no contracted SLA targets, contract terms or "
               "complaint tickets, so none are referenced.")
    return out
