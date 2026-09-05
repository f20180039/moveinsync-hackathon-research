"""Pure functions of their inputs. No I/O, no clock, no model.

This module is why the product is trustworthy: the reasoning is unit-testable,
and nothing here can produce a number the model influenced.
"""
from __future__ import annotations

from . import constants as C, references, registry
from .schemas import (Audience, Cause, Dimension, Direction, Finding, Metric,
                      Reference, ReferenceKind, Slice, Tier, Window, finding_id)


def _band_key(better: "Direction | None") -> str:
    """Which tuple in constants.BANDS judges this metric.

    Task 18: `better is None` is a metric with NO direction (a volume/demand
    reading -- Metric.is_two_sided), judged by distance from its reference in
    EITHER direction against BANDS["TWO_SIDED"]. It is not a missing value and
    must never be defaulted to HIGHER or LOWER: doing so would make the sweep
    blind to one of the two failures the metric exists to catch.
    """
    return "TWO_SIDED" if better is None else better.value


def delta(observed: float, reference: float, better: "Direction | None") -> float:
    """The shortfall as a fraction of the reference, signed so POSITIVE ALWAYS
    MEANS WORSE whichever way the metric points.

    Defining it this way removes the sign confusion a lower-is-better metric like
    sla_breach otherwise invites: one formula covers both directions, and gap is
    delta x reference, so its sign agrees with the tier by CONSTRUCTION rather
    than by care.

    One exception: each direction's PASS band (C.BANDS[better.value][0]) is a
    TOLERANCE, so a small POSITIVE delta can still tier PASS, which would
    leave a positive (accusatory) gap on a passing finding. That boundary
    case is not handled here -- it is floored to zero in evaluate_finding's
    PASS branch below, where the tier is known.

    Task 18, TWO-SIDED (better is None): there is no losing side, so the
    shortfall is the ABSOLUTE distance from the reference,
    |observed - reference| / |reference|. It is therefore never negative --
    a two-sided metric on its reference scores 0.0 and everything else scores
    the size of the move, in either direction. Which direction it moved is
    NOT thrown away: evaluate_finding records it as the Cause (DEMAND_SURGE
    above the reference, DEMAND_DROP below), because "book more vehicles" and
    "release vehicles" are opposite actions and a magnitude alone cannot
    choose between them.
    """
    if better is None:
        if reference == 0.0:
            return 0.0 if observed == 0.0 else 1.0
        return abs(observed - reference) / abs(reference)
    if reference == 0.0:
        if observed == 0.0:
            return 0.0
        return 1.0 if better is Direction.LOWER else -1.0
    shortfall = (reference - observed) if better is Direction.HIGHER else (observed - reference)
    return shortfall / abs(reference)


def tier_for(d: float, hard_target: bool, better: "Direction | None") -> Tier:
    # Deviation 2: a hard target admits no tolerance. Read literally, the spec's
    # "a TARGET missed outright -> BREACH" would make WATCH and CONCERN
    # unreachable for EVERY target metric.
    if hard_target:
        return Tier.BREACH if d > 0.0 else Tier.PASS
    # Fix round 1 (Task 5 review): one band per direction, not one global
    # scalar -- delta() saturates at 1.0 for a HIGHER-is-better metric, so a
    # CONCERN_MAX measured for LOWER-is-better no_show_rate (whose deltas are
    # genuinely unbounded) made BREACH unreachable for ota/otd/vendor_ota.
    # Keyed by better.value (a plain str) rather than the Direction enum
    # itself -- see constants.BANDS's comment for the circular-import reason.
    # Task 18: better=None (a two-sided metric) selects BANDS["TWO_SIDED"] --
    # see _band_key. Its delta is already an absolute distance, so the same
    # four-tier ladder applies unchanged; only the band tuple differs.
    pass_max, watch_max, concern_max = C.BANDS[_band_key(better)]
    if d <= pass_max:
        return Tier.PASS
    if d <= watch_max:
        return Tier.WATCH
    if d <= concern_max:
        return Tier.CONCERN
    return Tier.BREACH


def cause_for(kind: ReferenceKind) -> Cause:
    return {ReferenceKind.TARGET: Cause.BELOW_TARGET,
            ReferenceKind.TREND: Cause.TREND_REGRESSION,
            ReferenceKind.PEER: Cause.PEER_LAGGARD}[kind]


# Task 18: the two causes a TWO-SIDED metric fires. cause_for() above names
# WHICH REFERENCE fired; for a metric with no direction the useful thing to
# name is WHICH WAY IT MOVED, because that is what picks the action: demand
# above its reference means book more vehicles before employees are stranded,
# demand below it means release vehicles nobody is riding. The reference
# itself is still on the Finding (`refs`), so nothing is lost.
DEMAND_CAUSES = (Cause.DEMAND_SURGE, Cause.DEMAND_DROP)


def demand_cause(observed: float, reference: float) -> Cause:
    """Which side of its reference a two-sided metric landed on.

    Exactly-on-reference is DEMAND_DROP by the `>` below, which never reaches
    a reader: a zero delta tiers PASS, and a PASS carries Cause.ON_REFERENCE.
    """
    return Cause.DEMAND_SURGE if observed > reference else Cause.DEMAND_DROP


def cap_for_confidence(tier: Tier, confidence: float) -> Tier:
    """Low confidence caps severity; it never improves it."""
    if confidence >= C.MIN_TRUSTED_CONFIDENCE:
        return tier
    return Tier.WATCH if tier > Tier.WATCH else tier


def audiences_for(metric_id: str, slc: Slice, tier: Tier) -> frozenset[Audience]:
    """Assigned by rule, not by the model. A set, not one value: a BREACH assigns
    two and a single field would silently drop a recipient."""
    out = set()
    if tier is Tier.BREACH:
        out |= {Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER}
    # Controller ruling (task-4): the registry carries no cost_per_trip metric --
    # the facilities-head metric set is (vendor_ota, cost_per_km).
    if metric_id == "riders_per_day":
        # Task 18, user ruling: demand is a fleet-BOOKING decision and it is
        # named for both roles -- "so the transport and facilities manager can
        # be prepared in advance and not fall short of vendors and vice versa
        # not overbook vendors". The transport manager rosters the vehicles;
        # the facilities head owns the money when they are over- or
        # under-booked. Both, at every tier, not only at BREACH.
        out |= {Audience.TRANSPORT_MANAGER, Audience.FACILITIES_HEAD}
    elif metric_id in ("vendor_ota", "cost_per_km"):
        out.add(Audience.FACILITIES_HEAD)
    else:
        out.add(Audience.TRANSPORT_MANAGER)
    if slc.dim is Dimension.SHIFT:
        out.add(Audience.LINE_MANAGER)
    return frozenset(out)


def evaluate_finding(con, metric: Metric, slc: Slice, window: Window,
                     feed_confidence: float) -> Finding | None:
    observed = registry.evaluate(con, metric, slc, window)
    confidence = feed_confidence * registry.coverage(con, metric, slc, window)

    if observed is None:
        # An unmeasurable OVERALL metric is a finding — the agent is loud about
        # what it cannot read. An unmeasurable SLICE is not: a vendor that did not
        # operate this week is not news.
        if slc.dim is not Dimension.NONE:
            return None
        return Finding(finding_id(metric.id, slc, window), metric.id, slc, window,
                       0.0, (), Tier.WATCH, Cause.DATA_GAP, 0.0, confidence,
                       audiences_for(metric.id, slc, Tier.WATCH),
                       registry.evidence_sql(metric, slc, window))

    refs = references.resolve(con, metric, slc, window)
    if not refs:
        # An uncontextualised number is exactly what this product refuses to ship.
        return None

    # Deviation 3: keep every reference, take the WORST tier. cause and gap come
    # from the reference that produced it; ties keep the earlier-declared one.
    worst, firing, worst_delta = Tier.PASS, refs[0], float("-inf")
    for ref in refs:
        d = delta(observed, ref.value, metric.better)
        hard = metric.hard_target and ref.kind is ReferenceKind.TARGET
        t = tier_for(d, hard, metric.better)
        if t > worst or (t is worst and d > worst_delta):
            worst, firing, worst_delta = t, ref, d

    capped = cap_for_confidence(worst, confidence)
    if capped is not worst:
        cause = Cause.LOW_CONFIDENCE
    elif capped is Tier.PASS:
        cause = Cause.ON_REFERENCE
    elif metric.is_two_sided:
        # Task 18: for a metric with no direction, the cause names the SIDE
        # (which is what selects the action), not which reference fired.
        cause = demand_cause(observed, firing.value)
    else:
        cause = cause_for(firing.kind)

    # Deviation 1 holds for a two-sided metric too: worst_delta is already an
    # absolute distance there (verdict.delta), so gap stays POSITIVE-MEANS-
    # WORSE and the Cause -- not the sign -- says which way demand moved.
    gap = worst_delta * abs(firing.value)
    if capped is Tier.PASS:
        # Bug found running the full metric x slice sweep: each direction's
        # PASS band is a TOLERANCE, so tier_for(d) can still say PASS for a
        # small POSITIVE d (marginally worse than the reference but within
        # tolerance). Left
        # alone, gap = d x reference would be positive on a PASS finding,
        # which Finding.__post_init__ correctly refuses. Floor it at zero:
        # a PASS is reported as at-or-better, never as an accusation.
        gap = min(gap, 0.0)

    return Finding(finding_id(metric.id, slc, window), metric.id, slc, window,
                   observed, refs, capped, cause, gap,
                   confidence, audiences_for(metric.id, slc, capped),
                   registry.evidence_sql(metric, slc, window))


def rank(findings: list[Finding]) -> list[Finding]:
    """(tier desc, |gap| desc, confidence desc, id) — a TOTAL order.

    No arithmetic combines the keys, so no number of WATCHes can add up to a
    BREACH. The trailing id is not decoration: without a total order the sweep
    determinism test fails intermittently on ties, which is the worst kind of
    failure to debug at 15:00.
    """
    return sorted(findings, key=lambda f: (-f.tier.value, -abs(f.gap), -f.confidence, f.id))
