"""Pure functions of their inputs. No I/O, no clock, no model.

This module is why the product is trustworthy: the reasoning is unit-testable,
and nothing here can produce a number the model influenced.
"""
from __future__ import annotations

from . import constants as C, references, registry
from .schemas import (Audience, Cause, Dimension, Direction, Finding, Metric,
                      Reference, ReferenceKind, Slice, Tier, Window, finding_id)


def delta(observed: float, reference: float, better: Direction) -> float:
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
    """
    if reference == 0.0:
        if observed == 0.0:
            return 0.0
        return 1.0 if better is Direction.LOWER else -1.0
    shortfall = (reference - observed) if better is Direction.HIGHER else (observed - reference)
    return shortfall / abs(reference)


def tier_for(d: float, hard_target: bool, better: Direction) -> Tier:
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
    pass_max, watch_max, concern_max = C.BANDS[better.value]
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
    if metric_id in ("vendor_ota", "cost_per_km"):
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
    else:
        cause = cause_for(firing.kind)

    gap = worst_delta * firing.value
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
