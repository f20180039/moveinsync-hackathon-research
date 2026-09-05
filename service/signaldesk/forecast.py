"""Task 14 -- shift readiness outlook. A STATED SEASONAL BASELINE, not a model.

This is deliberately NOT machine learning and must never be presented as
prediction. For a target date it takes the SAME WEEKDAY from each of the last
four weeks, evaluates the metric on each of those four days through the
existing registry, and reports the recency-weighted mean of those four numbers
with an interval of +/- 1 standard deviation OF THOSE SAME FOUR OBSERVATIONS.

Nothing here is fitted, learned, or smoothed. Every projection carries
`method = "seasonal-baseline-4w"` and the four basis observations it averaged,
each with its date, its value and the literal SQL that produced it -- so a
judge asking "where does that number come from" gets four runnable queries,
not a coefficient.

The global constraint holds unchanged: the model never computes a number and
never writes raw SQL. Everything in this file is arithmetic over
`registry.evaluate()` results, and the readiness label reuses the EXISTING
bands in constants.BANDS through verdict.tier_for -- there is no second scale.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from . import references, registry, verdict
from .schemas import Dimension, Metric, Reference, Slice, Tier, Window

DAY_MS = 86_400_000

METHOD = "seasonal-baseline-4w"

# How many same-weekday basis days the method wants. Four is the plan's own
# number and matches references.TREND_WINDOWS, so the outlook and the trend
# reference look back over the same span of history.
BASIS_WEEKS = 4

# Recency weights, most recent basis day FIRST (i.e. WEIGHTS[0] applies to the
# day one week before the target, WEIGHTS[3] to the day four weeks before).
# 4/3/2/1 is a plain linear recency ramp, chosen because it is defensible out
# loud in one sentence: last week counts four times as much as the week before
# last month. It is stated, not fitted -- nothing in this repo tuned it.
WEIGHTS: tuple[int, ...] = (4, 3, 2, 1)

# Below this many basis days with data, the projection is WITHHELD rather than
# quietly averaged over whatever survived. A stated refusal is worth more than
# a confident number computed from one Tuesday.
MIN_BASIS_DAYS = 2

# How many of the run's ranked findings outlook_line() will try before giving
# up: each candidate costs four registry queries, and the brief needs one line.
BRIEF_CANDIDATES = 5

# Between MIN_BASIS_DAYS and BASIS_WEEKS the projection is still made, but the
# interval is WIDENED by this factor and the response says so. The spread of
# two days understates the spread of four; widening is the honest direction to
# be wrong in.
DEGRADED_WIDEN = 2.0

# The readiness label is a ONE-TO-ONE RENAME of the verdict Tier this
# projection lands in against the metric's own references -- NOT a second
# scale. The bands are constants.BANDS, unchanged, applied by
# verdict.tier_for exactly as a Finding's tier is. The words differ only
# because "is this shift ready" is the question the outlook answers.
READINESS_BY_TIER: dict[Tier, str] = {
    Tier.PASS: "READY",
    Tier.WATCH: "WATCH",
    Tier.CONCERN: "AT_RISK",
    Tier.BREACH: "NOT_READY",
}

# No projection, or no reference to judge one against.
READINESS_WITHHELD = "WITHHELD"
READINESS_UNJUDGED = "UNJUDGED"


def _date_label(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def _weekday(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%A")


def weighted_mean(values: list[float], weights: list[float]) -> float:
    """sum(w*v) / sum(w). Raises on an empty input rather than returning 0.0 --
    a zero here would read as a real projection of zero."""
    if not values:
        raise ValueError("weighted_mean needs at least one observation")
    total_w = float(sum(weights))
    if total_w == 0.0:
        raise ValueError("weighted_mean needs non-zero weights")
    return sum(w * v for w, v in zip(weights, values)) / total_w


def spread(values: list[float]) -> float:
    """Population standard deviation OF THE BASIS OBSERVATIONS THEMSELVES --
    around their own plain arithmetic mean, not around the weighted
    projection, and not a modelled variance. One observation has no spread, so
    it is 0.0 (and one observation is below MIN_BASIS_DAYS anyway)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


@dataclass(frozen=True)
class Basis:
    """One same-weekday basis day. `sql` is the literal-substituted query that
    produced `value` -- paste it into the DuckDB CLI and get this number."""
    date: str
    weekday: str
    start_ms: int
    end_ms: int
    weeks_back: int
    weight: int
    value: float | None
    sql: str


@dataclass(frozen=True)
class Projection:
    metric_id: str
    metric_label: str
    unit: str
    slice_label: str
    target_date: str
    target_start_ms: int
    projected: float | None
    interval_low: float | None
    interval_high: float | None
    readiness: str
    tier: Tier | None
    reference: Reference | None
    action: str
    note: str
    basis: tuple[Basis, ...]
    basis_days_used: int
    degraded: bool
    withheld: bool
    method: str = METHOD

    def to_json(self) -> dict:
        def _r(v, n=2):
            return round(v, n) if v is not None else None
        return {
            "metric": self.metric_id,
            "metricLabel": self.metric_label,
            "unit": self.unit,
            "slice": self.slice_label,
            "targetDate": self.target_date,
            "targetStartMs": self.target_start_ms,
            "projected": _r(self.projected),
            "intervalLow": _r(self.interval_low),
            "intervalHigh": _r(self.interval_high),
            "readiness": self.readiness,
            "tier": self.tier.name if self.tier is not None else None,
            "reference": (None if self.reference is None else {
                "kind": self.reference.kind.value,
                "label": self.reference.label,
                "value": _r(self.reference.value),
            }),
            "action": self.action,
            "method": self.method,
            "basisDaysUsed": self.basis_days_used,
            "degraded": self.degraded,
            "withheld": self.withheld,
            "note": self.note,
            "basis": [
                {"date": b.date, "weekday": b.weekday, "weeksBack": b.weeks_back,
                 "weight": b.weight, "value": _r(b.value),
                 "windowStartMs": b.start_ms, "windowEndMs": b.end_ms, "sql": b.sql}
                for b in self.basis
            ],
        }


# ---------------------------------------------------------------------------
# Rule-based actions, in the style of actions.py: a lookup, never a sentence
# the model originated. Tier selects urgency; the metric selects content.
# ---------------------------------------------------------------------------

# {metric_id: template}. Formatted with slice_label, weekday, date, value,
# unit, low, high.
_OUTLOOK_ACTIONS: dict[str, str] = {
    "ota": "Pre-brief the vendors serving {slice_label} for {weekday} {date}: the "
           "four-week same-weekday baseline puts on-time arrival near "
           "{value}{unit} ({low}-{high}{unit}).",
    "otd": "Check the release time against cab arrival for {slice_label} on "
           "{weekday} {date} -- the same-weekday baseline puts on-time departure "
           "near {value}{unit} ({low}-{high}{unit}).",
    "vendor_ota": "Confirm cover for {slice_label} before {weekday} {date}: the "
                  "same-weekday baseline puts its on-time share near {value}{unit} "
                  "({low}-{high}{unit}).",
    "cost_per_km": "Check the slab and contract mix for {slice_label} before "
                   "{weekday} {date} -- the same-weekday baseline puts cost per km "
                   "near {value} {unit} ({low}-{high}).",
    "cost_per_rider": "Check seat utilisation for {slice_label} on {weekday} "
                      "{date} -- the same-weekday baseline puts cost per rider "
                      "near {value} {unit} ({low}-{high}).",
    "late_pickup_rate": "Give the vendor's dispatch lead the routing for "
                        "{slice_label} on {weekday} {date}: the same-weekday "
                        "baseline puts late pickups near {value}{unit}.",
    "marshal_compliance": "Confirm marshal rostering for {slice_label} on "
                          "{weekday} {date} -- the same-weekday baseline puts "
                          "escort compliance near {value}{unit}, and the target "
                          "admits no shortfall.",
}

_READY_ACTION = ("Plan {slice_label} for {weekday} {date} as normal -- the "
                 "four-week same-weekday baseline puts {metric_label} near "
                 "{value}{unit}, inside its normal band.")

_WITHHELD_ACTION = ("No projection for {slice_label} on {weekday} {date}: only "
                    "{used} of {wanted} same-weekday basis days have data, below "
                    "the {minimum} this baseline will average over. Fix the feed "
                    "rather than plan against a number from one day.")


def _seat_action(con, slc: Slice, projected: float, basis: tuple[Basis, ...],
                 slice_label: str, weekday: str, date: str,
                 ready: bool = False) -> str:
    """no_show_rate's action names how many SEATS to release, not just a rate:
    planned headcount is the number a facilities head can actually act on.

    The seat count is projected the SAME WAY the rate is -- the recency-weighted
    mean of registry.planned_seats over the very same four basis days -- so the
    two halves of the sentence come from one method, not two.
    """
    seat_values, seat_weights = [], []
    for b in basis:
        if b.value is None:
            continue
        seats = registry.planned_seats(con, slc, Window(b.start_ms, b.end_ms))
        if seats > 0:
            seat_values.append(float(seats))
            seat_weights.append(float(b.weight))
    if not seat_values:
        return (f"Share the no-show list for {slice_label} before {weekday} {date}: "
                f"the same-weekday baseline puts no-shows near {projected:.1f}%, but "
                f"planned headcount for those days could not be read.")
    planned = weighted_mean(seat_values, seat_weights)
    seats_at_risk = round(planned * projected / 100.0)
    verb = "Hold the plan but budget for" if ready else "Release"
    return (f"{verb} about {seats_at_risk} of the ~{round(planned)} planned seats "
            f"for {slice_label} on {weekday} {date}, or confirm the riders: the "
            f"four-week same-weekday baseline puts no-shows near {projected:.1f}% "
            f"of planned headcount.")


def action_for_projection(con, metric: Metric, slc: Slice, p_projected: float | None,
                          tier: Tier | None, basis: tuple[Basis, ...],
                          slice_label: str, target_start_ms: int,
                          used: int, low: float | None, high: float | None) -> str:
    weekday, date = _weekday(target_start_ms), _date_label(target_start_ms)
    if p_projected is None:
        return _WITHHELD_ACTION.format(slice_label=slice_label, weekday=weekday,
                                       date=date, used=used, wanted=BASIS_WEEKS,
                                       minimum=MIN_BASIS_DAYS)
    fmt = dict(slice_label=slice_label, weekday=weekday, date=date,
               metric_label=metric.label, unit=metric.unit,
               value=f"{p_projected:.1f}",
               low=f"{low:.1f}" if low is not None else "?",
               high=f"{high:.1f}" if high is not None else "?")
    # no_show_rate names a SEAT COUNT at every readiness level, not only a bad
    # one: "about 40 of the ~1,400 planned seats will go unused" is the number
    # a facilities head plans against on a normal day too, and a rate alone is
    # not something anyone can release.
    if metric.id == "no_show_rate":
        return _seat_action(con, slc, p_projected, basis, slice_label, weekday, date,
                            ready=(tier is None or tier is Tier.PASS))
    if tier is None or tier is Tier.PASS:
        return _READY_ACTION.format(**fmt)
    template = _OUTLOOK_ACTIONS.get(metric.id)
    if not template:
        return (f"Review {slice_label} for {weekday} {date} before the shift is "
                f"rostered -- the same-weekday baseline puts {metric.label} near "
                f"{p_projected:.1f}{metric.unit}.")
    return template.format(**fmt)


# ---------------------------------------------------------------------------
# The projection itself.
# ---------------------------------------------------------------------------

def basis_days(con, metric: Metric, slc: Slice, target_start_ms: int) -> tuple[Basis, ...]:
    """The four same-weekday observations, most recent first. Each is one real
    `registry.evaluate()` over a one-day window, and carries the literal SQL
    that produced it."""
    out = []
    for i in range(BASIS_WEEKS):
        weeks_back = i + 1
        start = target_start_ms - weeks_back * 7 * DAY_MS
        window = Window(start, start + DAY_MS)
        value = registry.evaluate(con, metric, slc, window)
        out.append(Basis(_date_label(start), _weekday(start), start, start + DAY_MS,
                         weeks_back, WEIGHTS[i], value,
                         registry.evidence_sql(metric, slc, window)))
    return tuple(out)


def _readiness(con, metric: Metric, slc: Slice, projected: float,
               target_start_ms: int) -> tuple[Tier | None, Reference | None]:
    """The projection judged against the metric's OWN existing references for
    the last COMPLETE WEEK before the target date, through verdict.delta and
    verdict.tier_for -- the same two functions that tier a Finding, over the
    same constants.BANDS. Worst tier across the resolvable references wins,
    exactly as verdict.evaluate_finding does it.

    The reference window is the week ending at the target date rather than the
    basis days themselves: judging the baseline against its own inputs would be
    circular and would land on PASS by construction.
    """
    ref_window = Window(target_start_ms - 7 * DAY_MS, target_start_ms)
    refs = references.resolve(con, metric, slc, ref_window)
    if not refs:
        return None, None
    worst, firing, worst_delta = Tier.PASS, refs[0], float("-inf")
    for ref in refs:
        d = verdict.delta(projected, ref.value, metric.better)
        hard = metric.hard_target and ref.kind.name == "TARGET"
        t = verdict.tier_for(d, hard, metric.better)
        if t > worst or (t is worst and d > worst_delta):
            worst, firing, worst_delta = t, ref, d
    return worst, firing


def project(con, metric: Metric, slc: Slice, target_start_ms: int) -> Projection:
    """One metric x slice projected onto one target date.

    Degradation, in the order the plan states it:
      - fewer than MIN_BASIS_DAYS basis days with data -> WITHHELD, no number.
      - between MIN_BASIS_DAYS and BASIS_WEEKS -> projected, interval WIDENED
        by DEGRADED_WIDEN, `degraded` true, and `note` says which days are
        missing. It never silently averages fewer.
    """
    basis = basis_days(con, metric, slc, target_start_ms)
    have = [b for b in basis if b.value is not None]
    used = len(have)
    slice_label = slc.label
    target_date = _date_label(target_start_ms)

    if used < MIN_BASIS_DAYS:
        missing = ", ".join(b.date for b in basis if b.value is None)
        note = (f"Withheld: only {used} of {BASIS_WEEKS} same-weekday basis days "
                f"({_weekday(target_start_ms)}) returned a value for "
                f"{metric.label} on {slice_label} -- no data for {missing}. This "
                f"baseline will not average fewer than {MIN_BASIS_DAYS} days.")
        action = action_for_projection(con, metric, slc, None, None, basis,
                                       slice_label, target_start_ms, used, None, None)
        return Projection(metric.id, metric.label, metric.unit, slice_label,
                          target_date, target_start_ms, None, None, None,
                          READINESS_WITHHELD, None, None, action, note, basis,
                          used, used < BASIS_WEEKS, True)

    values = [b.value for b in have]
    weights = [float(b.weight) for b in have]
    projected = weighted_mean(values, weights)
    sd = spread(values)
    degraded = used < BASIS_WEEKS
    if degraded:
        sd *= DEGRADED_WIDEN
        missing = ", ".join(b.date for b in basis if b.value is None)
        note = (f"Degraded: {used} of {BASIS_WEEKS} same-weekday basis days had "
                f"data (no data for {missing}). The projection uses the "
                f"{used} that did, and the interval is widened "
                f"{DEGRADED_WIDEN:g}x because the spread of {used} days "
                f"understates the spread of {BASIS_WEEKS}.")
    else:
        note = (f"Weighted mean of the same weekday "
                f"({_weekday(target_start_ms)}) over the last {BASIS_WEEKS} "
                f"weeks, weights {'/'.join(str(w) for w in WEIGHTS)} most recent "
                f"first; interval is +/- 1 sd of those same {BASIS_WEEKS} "
                f"observations. Stated baseline, not a forecast.")

    low, high = projected - sd, projected + sd
    tier, reference = _readiness(con, metric, slc, projected, target_start_ms)
    readiness = READINESS_BY_TIER[tier] if tier is not None else READINESS_UNJUDGED
    if tier is None:
        note += (" No reference resolved for this slice, so the projection is "
                 "reported without a readiness label rather than given one.")
    action = action_for_projection(con, metric, slc, projected, tier, basis,
                                   slice_label, target_start_ms, used, low, high)
    return Projection(metric.id, metric.label, metric.unit, slice_label,
                      target_date, target_start_ms, projected, low, high,
                      readiness, tier, reference, action, note, basis,
                      used, degraded, False)


# ---------------------------------------------------------------------------
# The two endpoint-shaped entry points.
# ---------------------------------------------------------------------------

# Ordering for a readiness list: worst first, then the widest interval (the
# least certain of two equally bad days is the one to look at), then the id --
# a TOTAL order, so /api/outlook/shifts is deterministic across runs.
def _rank_key(p: Projection):
    tier_value = p.tier.value if p.tier is not None else -1
    width = (p.interval_high - p.interval_low) if p.interval_low is not None else -1.0
    return (-tier_value, -width, p.metric_id, p.slice_label)


def outlook(con, target_start_ms: int, metric_ids=None) -> list[Projection]:
    """Every named metric, overall slice, projected onto the target date."""
    ids = tuple(metric_ids) if metric_ids else registry.ACTIVE_METRICS
    out = [project(con, registry.by_id(mid), Slice.all(), target_start_ms) for mid in ids]
    return sorted(out, key=_rank_key)


def shift_outlook(con, target_start_ms: int, metric_id: str = "no_show_rate",
                  reference_window: Window | None = None) -> list[Projection]:
    """The shift readiness list: one projection per shift band.

    The shift bands come from `registry.distinct_values` over the week before
    the target date -- the bands the data actually carries, never a hardcoded
    list.
    """
    metric = registry.by_id(metric_id)
    window = reference_window or Window(target_start_ms - 7 * DAY_MS, target_start_ms)
    bands = registry.distinct_values(con, Dimension.SHIFT, window)
    out = [project(con, metric, Slice(Dimension.SHIFT, band), target_start_ms)
           for band in bands]
    return sorted(out, key=_rank_key)


# ---------------------------------------------------------------------------
# The brief line. compose.py calls this; it is deterministic and the model
# never writes it.
# ---------------------------------------------------------------------------

def outlook_line(con, run, metric_id: str | None = None) -> str | None:
    """One sentence for the brief, for the run's top finding's own metric x
    slice, projected onto the day after the run's window.

    It names the method as a BASELINE. The word "forecast" appears only as
    the explicit denial "(not a forecast)" and the word "predict" never
    appears at all: this is a stated average of four real days, and dressing
    it up as prediction would be a lie about the machinery.
    """
    findings = [f for f in run.findings if f.tier > Tier.PASS]
    if not findings:
        return None
    target = run.window.end_ms

    # Walk the ranked findings (worst first) and take the first one this
    # baseline can actually stand behind. A thin slice's same-weekday history
    # is often empty, and a refusal about the single worst finding is less
    # useful in a brief than a real baseline about the worst finding that HAS
    # four basis days. Bounded, because each candidate costs four queries.
    first = None
    for f in findings[:BRIEF_CANDIDATES]:
        p = project(con, registry.by_id(metric_id or f.metric_id), f.slice, target)
        if first is None:
            first = p
        if not p.withheld:
            break
    else:
        # Every candidate slice is too thin for a same-weekday baseline. Fall
        # back to the top finding's metric at the OVERALL slice before giving
        # up: a real baseline for the whole population, labelled "overall", is
        # more use in a brief than a refusal -- and the sentence names the
        # slice, so nobody can mistake it for a claim about the vendor.
        p = project(con, registry.by_id(metric_id or findings[0].metric_id),
                    Slice.all(), target)
        if p.withheld:
            p = first

    if p.withheld:
        return (f"outlook: no {BASIS_WEEKS}-week same-weekday baseline for "
                f"{p.slice_label} on {p.target_date} -- only {p.basis_days_used} "
                f"of {BASIS_WEEKS} basis days have data, so a number is withheld "
                f"rather than offered. This is a stated baseline, not a forecast.")
    metric = registry.by_id(p.metric_id)
    band = f"{p.interval_low:.1f}-{p.interval_high:.1f}{metric.unit}"
    return (f"outlook: the four-week same-weekday baseline (not a forecast) puts "
            f"{metric.label} for {p.slice_label} at about {p.projected:.1f}"
            f"{metric.unit} ({band}) on {_weekday(target)} {p.target_date} -- "
            f"{p.readiness}.")
