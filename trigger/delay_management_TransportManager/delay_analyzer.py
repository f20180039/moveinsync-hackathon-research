"""Deterministic analysis. No model, no network, no judgement calls.

The split this file exists to enforce: ARITHMETIC IS PYTHON'S. Minutes of
slip, which thresholds a ride crossed, how many contributing factors it has
-- all computed here, exactly and repeatably. The model is never asked to
subtract two timestamps; it is asked what the combination MEANS and what to
do about it. A number in a Slack escalation always came from this file.

Every threshold arrives from config (env-tunable). Every factor carries its
own minutes and a plain-English detail line, so the model and the Slack
message read the same facts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("trigger")

# A slip larger than this is corrupt data, not a late cab -- the sample
# carries at least one trip whose actual_start is ~58 days from its schedule.
# Such a value must degrade the row into a data-quality note, never become a
# "83,481 minute delay" in a Team Manager's Slack.
SANE_SLIP_MIN = 24 * 60

LOW, MEDIUM, HIGH, CRITICAL = "LOW", "MEDIUM", "HIGH", "CRITICAL"
_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3}

INFORMATIONAL = "Informational"
POTENTIAL_ISSUE = "Potential issue"
REQUIRES_ATTENTION = "Requires attention"
IMMEDIATE = "Immediate escalation"

_CRITICAL_ALERTS = ("PANIC_MOBILE", "PANIC_FIXED_DEVICE")


def _sane(minutes):
    """A slip we are willing to believe, or None."""
    if minutes is None:
        return None
    return minutes if abs(minutes) <= SANE_SLIP_MIN else None


def _factor(code, label, minutes, detail):
    return {"code": code, "label": label, "minutes": minutes, "detail": detail}


def analyze(ride: dict, cfg) -> dict:
    """One ride in, its deterministic picture out. Never raises: a ride with
    missing or unusable fields yields fewer factors and a data-quality note,
    not an exception."""
    factors, data_issues = [], []

    eta_dev = _sane(ride.get("etaDeviationMin"))
    if ride.get("etaDeviationMin") is not None and eta_dev is None:
        data_issues.append("arrival timestamps are implausible; ETA deviation ignored")
    start_slip = _sane(ride.get("driverStartSlipMin"))
    if ride.get("driverStartSlipMin") is not None and start_slip is None:
        data_issues.append("start timestamp is implausible; driver slip ignored")
    pickup_slip = _sane(ride.get("maxPickupSlipMin"))
    overdue = _sane(ride.get("overdueMin"))

    if ride.get("plannedArrivalLocal") is None:
        data_issues.append("no planned arrival time on this ride; ETA cannot be checked")

    # --- ETA deviation ---------------------------------------------------
    if eta_dev is not None and eta_dev >= cfg.eta_deviation_min:
        basis = ride.get("etaBasis")
        how = ("projected from the driver's actual start" if basis == "projected"
               else "measured against the actual arrival" if basis == "observed"
               else "against the plan")
        factors.append(_factor(
            "ETA_DEVIATION", "ETA deviation", eta_dev,
            f"expected arrival {ride.get('expectedArrivalLocal')} against a planned "
            f"{ride.get('plannedArrivalLocal')} — {eta_dev} min later, {how}"))

    # --- driver-side -----------------------------------------------------
    if start_slip is not None and start_slip >= cfg.driver_late_min:
        factors.append(_factor(
            "DRIVER_LATE_START", "Driver started late", start_slip,
            f"driver started {ride.get('actualStartLocal')} against a scheduled "
            f"{ride.get('scheduledStartLocal')} — {start_slip} min late"))
    if ride.get("delayReason") == "DRIVER":
        factors.append(_factor(
            "DRIVER_CAUSE", "Driver-attributed delay",
            ride.get("moveInSyncDelayMin"),
            "MoveInSync attributes this trip's delay to the driver"))
    if ride.get("driverNonCompliance"):
        factors.append(_factor("DRIVER_NON_COMPLIANCE", "Driver non-compliance", None,
                               "trip flagged is_driver_nc"))
    if ride.get("cabNonCompliance"):
        factors.append(_factor("CAB_NON_COMPLIANCE", "Cab non-compliance", None,
                               "trip flagged is_cab_nc"))

    # --- rider pickup ----------------------------------------------------
    if pickup_slip is not None and pickup_slip >= cfg.pickup_slip_min:
        factors.append(_factor(
            "PICKUP_SLIP", "Employee pickup slipped", pickup_slip,
            f"the worst pickup on this trip ran {pickup_slip} min behind plan"))

    # --- booking ---------------------------------------------------------
    # No booking timestamp exists in the dataset (see rides.py); an Adhoc
    # sign-in is a rider added outside the planned roster, which is the
    # closest honest signal for "booked late".
    if ride.get("adhocLegs"):
        factors.append(_factor(
            "LATE_BOOKING", "Late/ad-hoc booking", None,
            f"{ride['adhocLegs']} of {ride.get('legs')} riders joined as Adhoc "
            f"(outside the planned roster) rather than Planned"))
    if ride.get("cancelledLegs"):
        factors.append(_factor(
            "BOOKING_CANCELLED", "Booking cancelled from dashboard", None,
            f"{ride['cancelledLegs']} rider booking(s) cancelled after the trip was formed"))

    # --- riders who did not travel ---------------------------------------
    no_show = ride.get("noShowLegs") or 0
    if no_show >= cfg.noshow_legs_min:
        factors.append(_factor(
            "NO_SHOW_IMPACT", "Riders did not show", None,
            f"{no_show} rider(s) marked NO_SHOW against {ride.get('plannedRiders')} planned"))

    # --- safety / operational alerts --------------------------------------
    types = (ride.get("alertTypes") or "")
    severity = ride.get("worstAlertSeverity")
    if ride.get("alertCount"):
        factors.append(_factor(
            "SAFETY_ALERT", "Operational alert raised", None,
            f"{ride['alertCount']} alert(s): {types}"
            + (f", worst severity {severity}" if severity else "")))

    # --- still running past its planned arrival ---------------------------
    if overdue is not None and overdue >= cfg.eta_deviation_min and ride.get("status") == "IN_FLIGHT":
        factors.append(_factor(
            "OVERDUE", "Still running past planned arrival", overdue,
            f"{overdue} min past its planned arrival and not yet closed"))

    # --- capacity ---------------------------------------------------------
    riders, capacity = ride.get("actualRiders"), ride.get("cabCapacity")
    if riders is not None and capacity and riders > capacity:
        factors.append(_factor("CAPACITY_OVERFLOW", "More riders than seats", None,
                               f"{riders} riders against a {capacity}-seat cab"))

    severity_hint = _severity(factors, eta_dev, start_slip, types, severity, cfg)
    headline_min = max([f["minutes"] for f in factors if f["minutes"] is not None],
                       default=None)

    return {
        "rideId": ride.get("rideId"),
        "ride": ride,
        "factors": factors,
        "factorCodes": [f["code"] for f in factors],
        "delayMinutes": headline_min,
        "severityHint": severity_hint,
        "attentionHint": _attention(severity_hint),
        "primaryIssue": factors[0]["code"] if factors else None,
        "dataIssues": data_issues,
    }


def _severity(factors, eta_dev, start_slip, alert_types, alert_severity, cfg) -> str:
    """A deterministic floor the model may raise but never silently ignore.

    Deliberately conservative and explainable: a panic alert or a very large
    ETA slip is CRITICAL on its own; several smaller factors on one ride add
    up, because a ride that is late AND short-staffed AND alerting is not
    three small problems.
    """
    if not factors:
        return LOW
    level = LOW
    if eta_dev is not None:
        if eta_dev >= 3 * cfg.eta_deviation_min:
            level = CRITICAL
        elif eta_dev >= 2 * cfg.eta_deviation_min:
            level = max(level, HIGH, key=_ORDER.get)
        elif eta_dev >= cfg.eta_deviation_min:
            level = max(level, MEDIUM, key=_ORDER.get)
    if start_slip is not None and start_slip >= 2 * cfg.driver_late_min:
        level = max(level, HIGH, key=_ORDER.get)
    elif start_slip is not None and start_slip >= cfg.driver_late_min:
        level = max(level, MEDIUM, key=_ORDER.get)
    if any(a in (alert_types or "") for a in _CRITICAL_ALERTS):
        level = CRITICAL
    if alert_severity == "Sev-1":
        level = CRITICAL
    elif alert_severity == "Sev-2":
        level = max(level, HIGH, key=_ORDER.get)
    if len(factors) >= 3:
        level = max(level, HIGH, key=_ORDER.get)
    elif len(factors) >= 2:
        level = max(level, MEDIUM, key=_ORDER.get)
    return level


def _attention(severity: str) -> str:
    return {CRITICAL: IMMEDIATE, HIGH: REQUIRES_ATTENTION,
            MEDIUM: POTENTIAL_ISSUE, LOW: INFORMATIONAL}[severity]


def find_escalations(rides: list[dict], cfg) -> list[dict]:
    """Every ride with at least one factor, worst first. A malformed ride is
    logged and skipped -- it never stops the rest of the run."""
    out = []
    for ride in rides:
        try:
            a = analyze(ride, cfg)
        except Exception as exc:
            logger.warning("trigger: analysis failed for ride %s (%s)",
                           ride.get("rideId"), type(exc).__name__)
            continue
        if a["factors"]:
            out.append(a)
    out.sort(key=lambda a: (_ORDER[a["severityHint"]], a["delayMinutes"] or 0,
                            len(a["factors"])), reverse=True)
    return out
