"""What to do about a finding. Deterministic, keyed on the finding's own fields.

The model never writes these. An action line is the sentence a manager acts on,
and a hallucinated one is worse than none -- so it is a lookup, and the lookup is
tested. The model may re-word an action line when composing prose; it may not
originate one.

Controller ruling (task-8a): our live metric ids were ota, otd, vendor_ota,
no_show_rate, cost_per_km, with BELOW_TARGET handled for when a target
metric became active but none did yet. Task 11 activated marshal_compliance
-- the one hard target in the product -- so BELOW_TARGET is now reachable
for real (registry.py's own test:
test_marshal_compliance_is_the_one_hard_target_metric). Task 15 adds
late_pickup_rate and cost_per_rider (employee-related delay and cost).
There is no Cause.ANOMALY yet (it returns with Task 8c), so the two ANOMALY
entries the plan text sketched are dropped here rather than raising an
AttributeError on an enum member that does not exist.
"""
from __future__ import annotations

from .schemas import Cause, Finding, Tier

# (metric_id, cause) -> imperative. Tier selects urgency, not content: the thing
# to DO about a lagging vendor is the same at CONCERN and BREACH, only sooner.
_ACTIONS: dict[tuple[str, Cause], str] = {
    ("vendor_ota", Cause.PEER_LAGGARD):
        "Move volume off {slice_value} to the top-quartile vendors at this site, "
        "and put it on the next vendor review.",
    ("vendor_ota", Cause.TREND_REGRESSION):
        "Raise {slice_value}'s decline with the account manager before it reaches "
        "the SLA review -- it is trending, not a one-week blip.",
    ("ota", Cause.BELOW_TARGET):
        "Check the delay-reason split in the breakdown before escalating: driver "
        "delay is a vendor conversation, employee delay is a comms one, traffic "
        "is a routing one.",
    ("ota", Cause.PEER_LAGGARD):
        "Check which vendors serve {slice_value} -- the decomposition in the "
        "breakdown says who owns the shortfall -- before escalating the site.",
    ("ota", Cause.TREND_REGRESSION):
        "Check the delay-reason split in the breakdown before escalating "
        "{slice_value} -- a trend regression usually traces to one driver, "
        "traffic or employee cause, not a step change everywhere.",
    ("otd", Cause.TREND_REGRESSION):
        "Compare the affected shift's release time against cab arrival -- logout "
        "slippage is usually a dispatch-window problem, not a vendor one.",
    ("otd", Cause.PEER_LAGGARD):
        "Check which vendors serve {slice_value} -- the decomposition in the "
        "breakdown says who owns the shortfall -- before escalating the site.",
    ("no_show_rate", Cause.PEER_LAGGARD):
        "Share the no-show list with the line managers for {slice_value}; "
        "confirmed no-shows are billable capacity nobody used.",
    ("cost_per_km", Cause.PEER_LAGGARD):
        "Pull {slice_value}'s contract and slab mix against the peer median before "
        "the next billing cycle closes.",
    ("cost_per_km", Cause.TREND_REGRESSION):
        "Check what changed in {slice_value}'s own contract or slab mix before "
        "the next billing cycle -- this is a move against its own history, not "
        "a vendor comparison.",
    # Task 11: marshal_compliance is the one hard target in the product, so
    # this is the one place BELOW_TARGET is reachable today. A shortfall here
    # is not a metric miss -- the marshal-required population is derived from
    # dark hours + a female rider, or a WOMAN_TRAVELLING_ALONE alert, so a gap
    # is a real employee who should have had an escort and did not.
    ("marshal_compliance", Cause.BELOW_TARGET):
        "Audit escort sign-ins at {slice_value} for the affected trips. A female "
        "employee cannot board before a marshal signs in, so this is a safety "
        "breach and not a metric miss.",
    # Task 15: employee-related delay and cost. late_pickup_rate is the delay
    # an employee EXPERIENCES (their own pickup, late against their own
    # planned time) -- the action routes to the vendor/dispatch side on
    # purpose, because a rider cannot fix a driver arriving late to collect
    # them; that is a routing or driver-reporting problem, never a "tell the
    # employees to be ready sooner" one.
    ("late_pickup_rate", Cause.PEER_LAGGARD):
        "Share the late-pickup list for {slice_value} with the vendor's dispatch "
        "lead -- pickup slippage is a routing or driver-reporting problem, not "
        "an employee one.",
    ("late_pickup_rate", Cause.TREND_REGRESSION):
        "Compare {slice_value}'s late-pickup trend against the vendor's dispatch "
        "record before the next review -- pickup slippage usually traces to "
        "routing, not the workforce.",
    ("cost_per_rider", Cause.PEER_LAGGARD):
        "Check seat utilisation for {slice_value}: cost per rider rises when "
        "cabs run under-filled -- pair with the no-show list.",
    ("cost_per_rider", Cause.TREND_REGRESSION):
        "Look at what changed in cab occupancy for {slice_value} over the last "
        "few weeks -- a rising cost per rider usually means falling seat "
        "utilisation, not falling volume.",
}

# Fallback by cause alone, so a metric added later still says something useful
# rather than nothing.
_BY_CAUSE: dict[Cause, str] = {
    Cause.PEER_LAGGARD: "Compare {slice_value} against the peer median with the "
                        "vendor before the next review.",
    Cause.TREND_REGRESSION: "Look at what changed for {slice_value} in the last "
                            "week -- this is a move against its own history.",
    Cause.BELOW_TARGET: "Escalate {slice_value} against the agreed target.",
    Cause.LOW_CONFIDENCE: "Fix the upstream data for {slice_value} before acting "
                          "on this figure -- we are not confident in it.",
    Cause.DATA_GAP: "This could not be measured. Check the feed before drawing a "
                    "conclusion.",
    Cause.ON_REFERENCE: "",          # a PASS needs no action
}


def action_for(finding: Finding) -> str:
    """The imperative for this finding, or '' when none is warranted.

    A PASS returns '' deliberately -- inventing an action for something that is
    fine is how a brief becomes noise a manager learns to skim.
    """
    if finding.tier is Tier.PASS:
        return ""
    template = (_ACTIONS.get((finding.metric_id, finding.cause))
                or _BY_CAUSE.get(finding.cause, ""))
    if not template:
        return ""
    value = finding.slice.value or "this population"
    return template.format(slice_value=value)
