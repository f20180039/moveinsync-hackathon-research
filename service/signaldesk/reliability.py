"""Task 20 -- BOOKING RELIABILITY. Does a booked seat get used?

WHAT THIS IS. A per-employee score over ONE question: of the cab seats this
person was booked onto and could themselves have used or released, how many got
used? An unused booked seat is a seat the company has already paid a vendor
for, riding empty. Releasing it is worth real money, and it is the one thing a
rider actually controls.

WHAT THIS IS NOT, stated first because the name is the risk. It is NOT an
"employee quality" score, a productivity signal, a punctuality rating, or an
input to anything about a person's standing. It scores a BOOKING, not a booker.
Every identifier below is a means of counting seats, the cohorts are named for
what happened to the SEAT ("often unused"), never for what kind of person the
rider is, and the output text says so out loud so nobody downstream can quietly
re-frame it. It exists to release seats and cut waste.

THE THREE CONSTRAINTS, and how each is enforced rather than merely intended:

1. `gender` IS NEVER AN INPUT, directly or as a proxy. The column is right
   there on emp_legs and it stays out. registry.booking_reliability_legs does
   not select it, this module never sees it, and test_reliability.py greps both
   modules' source for it. DO NOT ADD IT LATER -- not as a feature, not as a
   "control", not as a cohort split. A score that reads gender is a
   discrimination engine wearing a metric's clothes.

2. NOBODY IS SCORED FOR SOMETHING OUTSIDE THEIR CONTROL. A late cab is the
   VENDOR's failure and appears nowhere in the numerator or the denominator.
   The full attribution ruling -- what counts, what is counted-but-not-
   attributed, and why late-to-pickup is absent altogether -- lives above
   _BOOKING_RELIABILITY_SQL in registry.py, because that is where the line is
   actually drawn. In one line: NO_SHOW counts; a dashboard cancellation and a
   NON_COMMUNICATING leg are reported as waste but attributed to nobody; a late
   pickup is not attributable to a rider from this data at all, so it is left
   out rather than guessed.

3. NO PERSON IS EVER BROADCAST. Following the precedent
   delay_management_TransportManager set -- "the model never sees a raw row, a
   `trip_id` join or an employee id" -- `summary()` and `narrative_line()`
   return AGGREGATES ONLY: cohort counts, site and shift-band rollups, seat
   totals. `stwid` appears in `employees()` for the API, and nowhere the model,
   a narrative or a Slack message can reach. There is a test that asserts a
   built summary's JSON contains no rider id.

THE SCORE

    score = 100 * used_legs / (used_legs + no_show_legs)

Higher is better; 100 means every booked seat this rider held was used. The
denominator is deliberately NOT the leg count: legs nobody can attribute (a
dashboard cancellation) are excluded from both halves, exactly as deviation 5
excludes an unmeasurable trip from both halves of an on-time rate rather than
guessing which way it went.

THIN DATA, handled the way the vendor scorecard handles it. An employee with
two legs is not a reliability signal -- with n attributable legs a single
no-show moves the score by 100/n points, so at n=2 one missed Tuesday reads as
a 50-point collapse. Below MIN_BOOKED_LEGS the score is WITHHELD and the rider
is reported in the NOT_ENOUGH_BOOKINGS cohort carrying the stated NEUTRAL
score, which is the population's own rate for the same window and slice -- "we
know nothing about this rider, so they read as typical". Both the floor and the
neutral value are named in the output; neither is silent.

MEASURED, data/real, sweep window 2026-07-25..2026-07-31, unsliced (the numbers
that chose the floor and the band edges -- see MIN_BOOKED_LEGS and BANDS):
18,861 riders carry a leg; 11,442 clear the floor; mean score 94.6; median 100;
p25 90.0; p10 83.3; p5 72.7. 6,986 booked seats went unused in that week.
597 scored riders (5.2% of scored) account for 1,986 of the 5,414 unused seats
held by scored riders (36.7% of those; 28.4% of all 6,986), and the 2,656
scored riders below 90 (23.2% of scored) account for 4,704 -- 86.9% of the
unused seats held by scored riders, and 67.3% of every unused seat in the
window, the figure `flaggedUnusedShare` reports. That concentration is the
whole argument for the score existing: unused seats are targetable, not
diffuse.

MEASURED, data/sample: NO rider clears the floor, in any window. The sample
carries at most 3 legs per rider over a week and 4 over four weeks (2 riders of
2,323 reach 4). The endpoint therefore returns an honest refusal on data/sample
rather than a table of neutral scores, and the tests assert that refusal rather
than pretending the fixture can support a per-person score.

Every figure here is Python arithmetic over registry counts. No model computes
any of it; chain-side prose is narration over a finished table, as everywhere
else in this repo.
"""
from __future__ import annotations

from .schemas import Dimension, Slice, Window

# ---------------------------------------------------------------------------
# The floor, and why it is 6 rather than the repo's MIN_ROWS_PER_SLICE (9).
#
# Different unit, so it needs its own number: MIN_ROWS_PER_SLICE guards a
# SLICE's trip/headcount population for a rate, and its value was pinned by
# what the committed sample fixture could support for a metric's TREND and PEER
# references (constants.py records that reasoning at length). This floor guards
# a PERSON's attributable-leg count.
#
# What actually constrained the choice, MEASURED on data/real over the sweep
# week (attributable legs per rider: p25 4, median 7, p75 9, p90 10, max 62):
#   * 4 keeps 14,837 of 18,861 riders (78.7%), but one no-show is 25 points --
#     a coin flip presented as a score.
#   * 6 keeps 11,442 (60.7%); one no-show is 16.7 points, two is 33.3.
#   * 9 (the MIN_ROWS_PER_SLICE value) keeps only 5,718 (30.3%), so the score
#     would speak for a minority of riders and stay silent about most of the
#     unused seats it exists to find.
# 6 is three round trips: enough that a habit and a single bad Tuesday do not
# look alike, low enough that the score covers most of the population. Stated,
# not fitted.
MIN_BOOKED_LEGS = 6

# The cohort ladder. FOUR bands, named for what happened to the SEAT -- never
# for what kind of person the rider is. "OFTEN_UNUSED" is a fact about a
# booking; "unreliable employee" would be a judgement about a colleague, and
# this score is not entitled to make one.
#
# MEASURED on data/real, sweep week, 11,442 scored riders: ALWAYS_USED 8,086
# (70.7%), USUALLY_USED 700 (6.1%), SOMETIMES_UNUSED 2,059 (18.0%),
# OFTEN_UNUSED 597 (5.2%). The edges are round numbers chosen so the bottom
# band is the ~5% tail that carries a third of all unused seats; the
# USUALLY_USED band is thin because at n=6..10 the achievable scores are coarse
# (5/6 = 83.3, 8/9 = 88.9, 9/10 = 90.0), which is a property of the data's leg
# counts and not a mis-set edge.
ALWAYS_USED = "ALWAYS_USED"
USUALLY_USED = "USUALLY_USED"
SOMETIMES_UNUSED = "SOMETIMES_UNUSED"
OFTEN_UNUSED = "OFTEN_UNUSED"
NOT_ENOUGH_BOOKINGS = "NOT_ENOUGH_BOOKINGS"

# (lower bound inclusive, cohort), best first.
BANDS: tuple[tuple[float, str], ...] = (
    (100.0, ALWAYS_USED),
    (90.0, USUALLY_USED),
    (75.0, SOMETIMES_UNUSED),
    (0.0, OFTEN_UNUSED),
)

# Worst first, so a rollup reads in the order a facilities head cares about.
COHORTS: tuple[str, ...] = (OFTEN_UNUSED, SOMETIMES_UNUSED, USUALLY_USED,
                            ALWAYS_USED, NOT_ENOUGH_BOOKINGS)

SCORED_COHORTS: tuple[str, ...] = (OFTEN_UNUSED, SOMETIMES_UNUSED,
                                   USUALLY_USED, ALWAYS_USED)

# The sentence every output carries, verbatim. It is a constant rather than
# prose written at each call site so that the framing cannot drift as the
# feature is extended, and so a test can assert it survives to the reader.
DISCLAIMER = (
    "Booking reliability measures whether a booked seat gets used, so unused "
    "seats can be released. It is not an employee performance or quality "
    "score. Gender is never an input. A late cab is the vendor's failure and "
    "is not counted here."
)


def score_for(used_legs: int, no_show_legs: int) -> float | None:
    """The score, or None when there is nothing attributable to score.

    None is a real answer -- a rider whose every leg in the window was a
    dashboard cancellation has no booking-reliability reading at all, and
    calling that 0 would blame them for the transport desk's action.
    """
    attributable = used_legs + no_show_legs
    if attributable <= 0:
        return None
    return 100.0 * used_legs / attributable


def cohort_for(score: float | None, attributable_legs: int) -> str:
    """The band a score lands in, or NOT_ENOUGH_BOOKINGS below the floor.

    The floor is checked BEFORE the bands, deliberately: a rider with one
    attributable leg and no no-show scores a perfect 100, and letting that
    through as ALWAYS_USED would put the thinnest evidence in the file into
    the most confident cohort.
    """
    if score is None or attributable_legs < MIN_BOOKED_LEGS:
        return NOT_ENOUGH_BOOKINGS
    for lower, name in BANDS:
        if score >= lower:
            return name
    return OFTEN_UNUSED                      # unreachable: BANDS ends at 0.0


def population_rate(rows) -> float | None:
    """The NEUTRAL score: the whole population's own booked-seat usage rate for
    this window and slice, over EVERY rider including those below the floor.

    Neutral means "no information", and the honest reading of no information
    about a rider is that they look like everybody else -- not that they are
    perfect (which would flatter), and not an arbitrary 50 (which on a
    population averaging ~95 would read as an accusation). It is computed from
    the same counts the scores are, so the two can never disagree about what a
    used seat is.
    """
    used = sum(r["used_legs"] for r in rows)
    no_show = sum(r["no_show_legs"] for r in rows)
    return score_for(used, no_show)


def _round(v, n=2):
    return round(v, n) if v is not None else None


def employees(rows, neutral: float | None) -> list[dict]:
    """Per-rider scores, worst scored first, then by unused seats.

    THE ONLY PLACE `stwid` SURVIVES. api.py may serve this; nothing that
    reaches the model, a narrative or Slack may. A rider below the floor
    carries `score: None` and the stated `neutral` separately, so a reader can
    never mistake the fallback for a measurement.
    """
    out = []
    for r in rows:
        attributable = r["used_legs"] + r["no_show_legs"]
        score = score_for(r["used_legs"], r["no_show_legs"])
        cohort = cohort_for(score, attributable)
        scored = cohort != NOT_ENOUGH_BOOKINGS
        out.append({
            "stwid": r["stwid"],
            "bookedLegs": attributable,
            "usedLegs": r["used_legs"],
            "unusedLegs": r["no_show_legs"],
            "notAttributedLegs": r["not_attributed_legs"],
            "legs": r["legs"],
            "score": _round(score) if scored else None,
            "neutralScore": None if scored else _round(neutral),
            "cohort": cohort,
            "scored": scored,
        })
    # Worst first among the scored; unscored riders last, since they carry no
    # finding. Total order (stwid breaks ties) so the response is deterministic.
    out.sort(key=lambda e: (not e["scored"],
                            e["score"] if e["score"] is not None else 0.0,
                            -e["unusedLegs"], e["stwid"]))
    return out


def rollup(rows, neutral: float | None) -> dict:
    """Cohort counts and seat totals for a set of per-rider counts. AGGREGATE
    ONLY -- no identifier of any kind comes out of this function, which is what
    makes it safe to put in front of a manager or a model."""
    counts = {c: 0 for c in COHORTS}
    unused_by_cohort = {c: 0 for c in COHORTS}
    scored_used = scored_unused = 0
    scores = []
    for r in rows:
        attributable = r["used_legs"] + r["no_show_legs"]
        score = score_for(r["used_legs"], r["no_show_legs"])
        cohort = cohort_for(score, attributable)
        counts[cohort] += 1
        unused_by_cohort[cohort] += r["no_show_legs"]
        if cohort != NOT_ENOUGH_BOOKINGS:
            scored_used += r["used_legs"]
            scored_unused += r["no_show_legs"]
            scores.append(score)
    scores.sort()
    scored = len(scores)
    unused_total = sum(r["no_show_legs"] for r in rows)
    # The concentration figure: what share of the unused seats sit with the
    # riders the score can actually speak for and flags. This is the number
    # that says whether targeting is worth doing at all.
    flagged_unused = unused_by_cohort[OFTEN_UNUSED] + unused_by_cohort[SOMETIMES_UNUSED]
    return {
        "riders": len(rows),
        "ridersScored": scored,
        "ridersBelowFloor": counts[NOT_ENOUGH_BOOKINGS],
        "cohorts": {c: counts[c] for c in COHORTS},
        "unusedSeatsByCohort": {c: unused_by_cohort[c] for c in COHORTS},
        "unusedSeats": unused_total,
        "usedSeats": sum(r["used_legs"] for r in rows),
        "notAttributedSeats": sum(r["not_attributed_legs"] for r in rows),
        "meanScore": _round(sum(scores) / scored) if scored else None,
        "medianScore": _round(scores[scored // 2] if scored % 2
                              else (scores[scored // 2 - 1] + scores[scored // 2]) / 2)
                       if scored else None,
        "scoredUsedSeats": scored_used,
        "scoredUnusedSeats": scored_unused,
        "flaggedUnusedSeats": flagged_unused,
        "flaggedRiders": counts[OFTEN_UNUSED] + counts[SOMETIMES_UNUSED],
        "flaggedUnusedShare": _round(flagged_unused / unused_total, 4) if unused_total else None,
        "neutralScore": _round(neutral),
    }


# Which slices a manager-facing rollup is cut by. SITE and SHIFT are the two
# the request named; both are Dimensions the registry already supports, so
# adding TENANT or MODE later is a one-entry change and needs no new SQL.
ROLLUP_DIMS: tuple[Dimension, ...] = (Dimension.SITE, Dimension.SHIFT)


def summary(con, window: Window, dims: tuple[Dimension, ...] = ROLLUP_DIMS,
            slc: Slice | None = None) -> dict:
    """The whole picture for a window: the overall rollup plus one rollup per
    value of each requested dimension. NO RIDER IDENTIFIER APPEARS ANYWHERE IN
    THE RETURN VALUE -- this is the shape that may be shown to a manager, sent
    to Slack, or handed to a model to narrate.

    `registry` is imported inside the function rather than at module scope: it
    imports duckdb and the whole metric table, and reliability.py's pure
    arithmetic (score_for/cohort_for/rollup) is worth being able to import and
    test without any of that.
    """
    from . import registry

    slc = slc or Slice.all()
    rows = registry.booking_reliability_legs(con, slc, window)
    neutral = population_rate(rows)
    overall = rollup(rows, neutral)

    by_dim: dict[str, list[dict]] = {}
    for dim in dims:
        grouped: dict[str, list[dict]] = {}
        for r in registry.booking_reliability_legs_by_dim(con, dim, window):
            grouped.setdefault(r["group"], []).append(r)
        entries = []
        for value, group_rows in grouped.items():
            entry = rollup(group_rows, population_rate(group_rows))
            entry["value"] = value
            entries.append(entry)
        # Worst first: most unused seats the score can speak for, then most
        # unused seats overall, then the name -- a total order, so the
        # response is byte-identical across runs on identical data.
        entries.sort(key=lambda e: (-e["flaggedUnusedSeats"], -e["unusedSeats"],
                                    str(e["value"])))
        by_dim[dim.name] = entries

    return {
        "window": {"start": window.start_ms, "end": window.end_ms,
                   "label": window.label},
        "slice": slc.label,
        "minBookedLegs": MIN_BOOKED_LEGS,
        "neutralScore": _round(neutral),
        "neutralScoreBasis": (
            f"the population's own booked-seat usage rate for {window.label}"
            + ("" if slc.dim is Dimension.NONE else f" ({slc.label})")),
        "bands": [{"cohort": name, "minScore": lower} for lower, name in BANDS],
        "overall": overall,
        "byDimension": by_dim,
        # Stated in the payload, not only in a docstring: an API consumer that
        # renders a per-site table has to know why the site rider counts do not
        # add up to the overall one.
        "notes": [
            DISCLAIMER,
            f"A rider is scored only with at least {MIN_BOOKED_LEGS} "
            f"attributable booked legs in the window. Below that the score is "
            f"withheld and the rider is reported as {NOT_ENOUGH_BOOKINGS} "
            f"against the stated neutral score, which is the population's own "
            f"rate for this window.",
            "Legs nobody can attribute -- a booking cancelled from the "
            "transport desk's dashboard, or a NON_COMMUNICATING leg -- are "
            "counted as wasted seats but are excluded from every score, "
            "numerator and denominator.",
            "A rider who travels from more than one site is counted under each "
            "of them, so per-site rider counts do not sum to the overall "
            "count.",
        ],
        "disclaimer": DISCLAIMER,
    }


def narrative_line(s: dict) -> str | None:
    """One deterministic sentence for a brief or a Slack message. AGGREGATE
    ONLY, and it names the framing every time so the number cannot travel
    without it. None when nothing clears the floor -- an honest silence, not a
    sentence about zero people.

    Written in Python, like every other figure in this repo; a model may quote
    it and may not recompute it.
    """
    o = s["overall"]
    if not o["ridersScored"]:
        return (f"booking reliability: no rider in {s['window']['label']} has "
                f"the {s['minBookedLegs']} attributable booked legs this score "
                f"needs, so no score is reported. {o['unusedSeats']} booked "
                f"seats went unused across {o['riders']} riders.")
    flagged_share = o["flaggedUnusedShare"]
    share = f" ({flagged_share * 100:.0f}% of all unused booked seats)" \
        if flagged_share is not None else ""
    return (f"booking reliability: {o['ridersScored']} riders clear the "
            f"{s['minBookedLegs']}-leg floor, median score "
            f"{o['medianScore']:.0f}/100; {o['flaggedRiders']} of them sit "
            f"below {BANDS[1][0]:.0f} and account for "
            f"{o['flaggedUnusedSeats']} unused booked seats{share}. "
            f"Seats, not people: this measures whether a booked seat gets "
            f"used, and gender is never an input.")
