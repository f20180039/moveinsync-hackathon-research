"""The scoring model -- deterministic, peer-relative, and documented here so
a Facilities Head can argue with the weights rather than guess at them.

THREE DIMENSIONS, each 0-100.

1. SERVICE (what the vendor delivered)
       0.45 x on-time %            MoveInSync's delay_minutes <= 5
     + 0.30 x SLA adherence %      delay_minutes <= 15 (constants.SLA_BREACH_MS)
     + 0.15 x completion %         trips with a recorded arrival
     + 0.10 x rider rating         mean of route/driver/safety, scaled 1-5 -> 0-100
   Ratings are dropped and the remaining weights renormalised when a vendor
   has no feedback in the window -- an unrated vendor is not penalised for
   silence.

2. RELIABILITY (whether it delivered CONSISTENTLY)
       0.50 x consistency          100 - 2 x (standard deviation of daily
                                   on-time %), floored at 0
     + 0.30 x good-day share       100 - % of days below the poor-day line
     + 0.20 x operational cleanliness
                                   100 - (no-show % + alerts per 100 trips
                                   + driver non-compliance %), floored at 0
   Days with fewer than 3 trips are excluded from the daily series: one trip
   at 0% is one trip, not a bad day. A vendor with fewer than 2 rated days
   scores consistency at the neutral 50 and the report says so.

3. COST VALUE (what that service cost, against its peers)
   Centred on the PEER MEDIAN cost per ON-TIME trip, because cost per trip
   flatters a vendor that runs cheap trips late:
       score = 50 + 50 x (median - vendor) / median,  clamped to 0-100
   At the median a vendor scores 50; at half the median 100; at twice the
   median 0. Peer-relative by construction, so it says "expensive for what
   this programme pays", never "expensive" in the abstract.
   With no cost data the dimension is None, the overall score is computed
   from the other two renormalised, and every report states that
   value-for-money could not be assessed on price.

OVERALL = 0.40 x service + 0.30 x reliability + 0.30 x cost value
(weights are `VENDOR_W_*` env vars). Because cost value is centred at 50 by
construction, overall scores sit below service scores -- that is the model
working, not a bug: it is a RANKING instrument, and every vendor is on the
same scale.

TREND is measured, never averaged away: the window is split into its natural
parts (months in a quarter, thirds of a month) and the first is compared with
the last. A vendor at 95% then 91% then 83% is deteriorating even though its
average is a healthy 89.7%.

CONFIDENCE is deterministic, from evidence volume -- trips, parts of the
window with data, and cost coverage. The model may not raise it.
"""
from __future__ import annotations

from .metrics import vendor_metrics

IMPROVING, STABLE, DETERIORATING, VOLATILE, INSUFFICIENT = (
    "IMPROVING", "STABLE", "DETERIORATING", "VOLATILE", "INSUFFICIENT_DATA")

# Recommendation vocabulary -- fixed, so the Slack report and any downstream
# system speak the same language and the model cannot invent a new verdict.
CONTINUE_INCREASE = "CONTINUE — INCREASE ALLOCATION"
CONTINUE_PREFER = "CONTINUE — PREFERRED"
CONTINUE_PLAIN = "CONTINUE"
MONITOR = "CONTINUE — PERFORMANCE MONITORING"
REVIEW = "REVIEW CONTRACT"
REDUCE = "REDUCE ALLOCATION"
REPLACE = "CONSIDER REPLACEMENT"
RECOMMENDATIONS = (CONTINUE_INCREASE, CONTINUE_PREFER, CONTINUE_PLAIN, MONITOR,
                   REVIEW, REDUCE, REPLACE)

PREFERRED, STRATEGIC, BACKUP, POOR_VALUE, UNKNOWN_VALUE = (
    "PREFERRED VENDOR", "STRATEGIC — LOW COST, STRONG SERVICE",
    "BACKUP / TACTICAL", "POOR VALUE", "NOT ASSESSABLE (no cost data)")


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def service_score(v: dict) -> float:
    parts = [(0.45, v["onTimePct"]), (0.30, v["slaAdherencePct"]),
             (0.15, v["completionPct"])]
    ratings = [r for r in (v["routeRating"], v["driverRating"], v["safetyRating"])
               if r is not None]
    if ratings and v["ratingResponses"]:
        parts.append((0.10, _clamp(sum(ratings) / len(ratings) / 5.0 * 100)))
    usable = [(w, x) for w, x in parts if x is not None]
    if not usable:
        return 0.0
    total_w = sum(w for w, _ in usable)
    return round(sum(w * x for w, x in usable) / total_w, 1)


def reliability_score(v: dict, cfg) -> tuple[float, str | None]:
    caveat = None
    if v["onTimeVolatility"] is None:
        consistency, caveat = 50.0, "too few rated days to measure consistency"
    else:
        consistency = _clamp(100 - 2 * v["onTimeVolatility"])
    good_days = (_clamp(100 - 100.0 * v["poorDays"] / v["ratedDays"])
                 if v["ratedDays"] else 50.0)
    penalties = ((v["noShowPct"] or 0) + (v["alertsPer100Trips"] or 0)
                 + 100.0 * v["driverNonCompliance"] / max(v["trips"], 1))
    clean = _clamp(100 - penalties)
    return round(0.50 * consistency + 0.30 * good_days + 0.20 * clean, 1), caveat


def cost_value_score(v: dict, peer_median) -> tuple[float | None, str | None]:
    if v["costPerOnTimeTrip"] is None or not peer_median:
        return None, "no cost data for this vendor in the window"
    score = 50 + 50 * (peer_median - v["costPerOnTimeTrip"]) / peer_median
    return round(_clamp(score), 1), None


def _trend_of(series: list[float | None], min_change: float) -> str:
    usable = [s for s in series if s is not None]
    if len(usable) < 2:
        return INSUFFICIENT
    change = usable[-1] - usable[0]
    if len(usable) >= 3:
        swings = max(usable) - min(usable)
        if swings >= 3 * min_change and abs(change) < min_change:
            return VOLATILE
    if change <= -min_change:
        return DETERIORATING
    if change >= min_change:
        return IMPROVING
    return STABLE


def trend(con, vendor: str, windows, cfg) -> dict:
    """On-time and cost-per-on-time-trip across the window's own parts."""
    on_time, cost, labels = [], [], []
    for w in windows:
        rows = {m["vendor"]: m for m in vendor_metrics(con, w, cfg)}
        m = rows.get(vendor)
        labels.append(w.label)
        on_time.append(m["onTimePct"] if m else None)
        cost.append(m["costPerOnTimeTrip"] if m else None)
    return {
        "labels": labels,
        "onTimeSeries": on_time,
        "costPerOnTimeSeries": cost,
        "onTimeTrend": _trend_of(on_time, 2.0),          # percentage points
        # Cost RISING is bad, so the sign is flipped before classifying.
        "costTrend": _trend_of([-c if c is not None else None for c in cost],
                               max(0.05 * (cost[0] or 1), 1.0)),
        "onTimeChangePP": (round(on_time[-1] - on_time[0], 1)
                           if on_time and on_time[0] is not None
                           and on_time[-1] is not None else None),
        "costChangePct": (round(100.0 * (cost[-1] - cost[0]) / cost[0], 1)
                          if cost and cost[0] and cost[-1] else None),
    }


def confidence(v: dict, parts_with_data: int, total_parts: int) -> tuple[str, str]:
    """Deterministic, from evidence volume. The model may not raise this."""
    reasons = []
    level = "HIGH"
    if v["trips"] < 30:
        level = "MEDIUM"
        reasons.append(f"{v['trips']} trips in the window")
    if v["trips"] < 10:
        level = "LOW"
    if total_parts > 1 and parts_with_data < total_parts:
        level = "LOW" if level == "MEDIUM" else "MEDIUM"
        reasons.append(f"active in {parts_with_data} of {total_parts} periods")
    if v["costCoveragePct"] is None or v["costCoveragePct"] < 80:
        level = "LOW" if level == "MEDIUM" else "MEDIUM"
        reasons.append(f"cost data on {v['costCoveragePct'] or 0}% of trips")
    return level, "; ".join(reasons) or "full evidence across the window"


def value_quadrant(v: dict, peer_cost_median, peer_service_median) -> str:
    if v["costPerOnTimeTrip"] is None or not peer_cost_median:
        return UNKNOWN_VALUE
    dear = v["costPerOnTimeTrip"] > peer_cost_median
    good = v["scores"]["service"] >= peer_service_median
    if good and not dear:
        return STRATEGIC
    if good and dear:
        return PREFERRED
    if not good and not dear:
        return BACKUP
    return POOR_VALUE


def _recommend(v: dict, rank: int, of: int) -> tuple[str, list[str]]:
    """The deterministic recommendation FLOOR. The model writes the narrative
    and may move the verdict one notch with evidence; it does not invent one
    from nothing."""
    s = v["scores"]
    overall, trend_state = s["overall"], v["trend"]["onTimeTrend"]
    evidence = []
    if v["trend"]["onTimeChangePP"] is not None:
        evidence.append(f"on-time moved {v['trend']['onTimeChangePP']:+.1f} pp "
                        f"across the window")
    if v["trend"]["costChangePct"] is not None:
        evidence.append(f"cost per on-time trip moved "
                        f"{v['trend']['costChangePct']:+.1f}%")
    evidence.append(f"overall score {overall}/100, rank {rank} of {of}")
    if v["quadrant"] != UNKNOWN_VALUE:
        evidence.append(f"value position: {v['quadrant'].lower()}")

    deteriorating = trend_state == DETERIORATING
    if overall >= 75 and not deteriorating:
        return (CONTINUE_INCREASE if rank <= 2 else CONTINUE_PREFER), evidence
    if overall >= 60:
        return (MONITOR if deteriorating else CONTINUE_PLAIN), evidence
    if overall >= 45:
        return (REVIEW if v["quadrant"] == POOR_VALUE else MONITOR), evidence
    if v["quadrant"] == POOR_VALUE or deteriorating:
        return REPLACE, evidence
    return REDUCE, evidence


def build(con, window, sub_windows, cfg, min_trips=None) -> dict:
    """The full deterministic picture for a window: metrics, scores, trends,
    quadrants, ranking, recommendation floors and confidence.

    `min_trips` overrides the ranking floor: a month or a quarter wants
    `cfg.min_trips` (9, the repo's own MIN_ROWS_PER_SLICE), but on ONE day
    that floor would leave almost every vendor unranked.
    """
    floor = cfg.min_trips if min_trips is None else min_trips
    vendors = vendor_metrics(con, window, cfg)
    if not vendors:
        return {"vendors": [], "ranked": [], "unranked": [], "peers": {}}

    cost_median = _median([v["costPerOnTimeTrip"] for v in vendors])

    for v in vendors:
        svc = service_score(v)
        rel, rel_caveat = reliability_score(v, cfg)
        cost, cost_caveat = cost_value_score(v, cost_median)
        weights = [(cfg.w_service, svc), (cfg.w_reliability, rel)]
        if cost is not None:
            weights.append((cfg.w_cost, cost))
        total_w = sum(w for w, _ in weights)
        v["scores"] = {
            "service": svc, "reliability": rel, "costValue": cost,
            "overall": round(sum(w * x for w, x in weights) / total_w, 1),
        }
        v["scoreCaveats"] = [c for c in (rel_caveat, cost_caveat) if c]
        v["trend"] = (trend(con, v["vendor"], sub_windows, cfg) if sub_windows
                      else {"labels": [], "onTimeSeries": [], "costPerOnTimeSeries": [],
                            "onTimeTrend": INSUFFICIENT, "costTrend": INSUFFICIENT,
                            "onTimeChangePP": None, "costChangePct": None})

    service_median = _median([v["scores"]["service"] for v in vendors])
    for v in vendors:
        v["quadrant"] = value_quadrant(v, cost_median, service_median)

    ranked = sorted([v for v in vendors if v["trips"] >= floor],
                    key=lambda v: v["scores"]["overall"], reverse=True)
    unranked = [v for v in vendors if v["trips"] < floor]

    parts = len(sub_windows) if sub_windows else 1
    for i, v in enumerate(ranked, start=1):
        v["rank"] = i
        with_data = sum(1 for s in v["trend"]["onTimeSeries"] if s is not None) or 1
        v["confidence"], v["confidenceReason"] = confidence(v, with_data, parts)
        v["recommendationFloor"], v["evidence"] = _recommend(v, i, len(ranked))
    for v in unranked:
        v["rank"] = None
        v["confidence"], v["confidenceReason"] = confidence(v, 1, parts)
        v["recommendationFloor"] = MONITOR
        v["evidence"] = [f"only {v['trips']} trips in the window — "
                         f"below the {floor}-trip ranking floor"]

    return {
        "vendors": vendors, "ranked": ranked, "unranked": unranked,
        "peers": {"costPerOnTimeMedian": cost_median,
                  "serviceScoreMedian": service_median},
    }
