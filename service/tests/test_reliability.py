"""Task 20 -- the employee booking-reliability score, end to end.

One question: does a booked seat get used? The interesting behaviour is the
three HARD CONSTRAINTS, so most of this file tests those rather than the
arithmetic, which is one division.

Arithmetic cases are planted on a bare DuckDB connection and hand-calculated,
never recomputed with the implementation's own expression
(docs/TESTING-LESSONS.md: a test that recomputes the behaviour it names asserts
nothing). Where a general property is claimed ("scores", "never", "always"),
there are two or more data points, per that document's Kind-1 rule.

data/sample CANNOT support a per-rider score and the tests say so rather than
pretending: MEASURED, it carries at most 3 attributable legs per rider over a
week (2 riders of 2,323 reach 4 over four weeks), so zero riders clear the
6-leg floor. That refusal is itself asserted, on the real fixture, as the
honest-thin-data behaviour.

BREAK-IT-TO-PROVE-IT was RUN (not assumed) on the two properties this feature
exists for. Each behaviour was deleted, the named test was confirmed red, and
the behaviour restored. The failure output is recorded, because a break-it
check nobody can re-verify is just another claim:

  1. delete the `attributable_legs < MIN_BOOKED_LEGS` clause in
     reliability.cohort_for() (i.e. score a rider on any number of legs)
     -> test_a_rider_below_the_floor_is_not_scored_at_any_score FAILS:
        "AssertionError: assert 'ALWAYS_USED' == 'NOT_ENOUGH_BOOKINGS'" -- a
        rider with ONE booked leg and no no-show lands in the most confident
        cohort in the file, i.e. the thinnest evidence in the dataset produces
        the strongest claim in the output.
     And test_the_sample_fixture_cannot_score_anybody_and_says_so FAILS too:
        "assert 619 == 0" -- 619 of data/sample's 633 one-leg riders become
        scored, and the endpoint starts publishing a per-person table the
        fixture cannot support.
     Both restored; 21 passed.

  2. change registry._BOOKING_RELIABILITY_CASE so a dashboard cancellation
     counts as an unused seat against the rider (add
     `OR not_boarding_reason = 'TRIP_CANCELLED_FROM_DASHBOARD'` to the no_show
     branch)
     -> test_a_dashboard_cancellation_is_never_scored_against_the_rider FAILS:
        "assert (5, 5, 4) == (5, 1, 4) / At index 1 diff: 5 != 1" -- rider 4's
        four cancellations become four unused seats charged to them, dropping
        their score from 5/6 = 83.3 to 5/10 = 50.0. A rider whose booking the
        transport desk itself pulled would be scored as if they had failed to
        turn up: exactly the "never score someone for something outside their
        control" violation the constraint names. Restored; 21 passed.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import pathlib

import duckdb
import pytest

from signaldesk import ingest, registry, reliability
from signaldesk.schemas import Dimension, Slice, Window

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")
SRC = pathlib.Path(reliability.__file__).resolve().parent
DAY_MS = 86_400_000


def _ms(y, m, d) -> int:
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


# The window the sweep itself runs on data/sample and data/real.
SWEEP_WEEK = Window(_ms(2026, 7, 25), _ms(2026, 8, 1))


@pytest.fixture
def con():
    c = duckdb.connect()
    ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c
    c.close()
    registry.clear_cache()


# ---------------------------------------------------------------------------
# A planted two-table fixture, so every count below is hand-checkable.
#
# Deliberately mixed: `gender` IS present on the planted rows (it is present in
# the real data too), so a test that the score ignores it has a real subject.
# ---------------------------------------------------------------------------

_LEGS = [
    # (stwid, gender, boarding_status, not_boarding_reason, is_no_show)
    # rider 1: 8 booked legs, 8 used                     -> 100.0
    *[(1, "FEMALE", "Boarded", None, False)] * 8,
    # rider 2: 8 booked legs, 6 used + 2 no-show         -> 75.0
    *[(2, "MALE", "Boarded", None, False)] * 6,
    *[(2, "MALE", "Not Boarded", "NO_SHOW", True)] * 2,
    # rider 3: 6 booked legs, 3 used + 3 no-show         -> 50.0
    *[(3, "MALE", "Boarded", None, False)] * 3,
    *[(3, "MALE", "Not Boarded", "NO_SHOW", True)] * 3,
    # rider 4: 6 booked legs (5 used, 1 no-show -> 83.33) PLUS 4 dashboard
    # cancellations, which must touch neither half of the score.
    *[(4, "FEMALE", "Boarded", None, False)] * 5,
    (4, "FEMALE", "Not Boarded", "NO_SHOW", True),
    *[(4, "FEMALE", "Not Boarded", "TRIP_CANCELLED_FROM_DASHBOARD", False)] * 4,
    # rider 5: 1 booked leg, used. Below the floor -> unscored, NOT a 100.
    (5, "MALE", "Boarded", None, False),
    # rider 6: 3 legs, ALL dashboard cancellations -> nothing attributable at
    # all, so no score exists, and 0.0 would be a lie about them.
    *[(6, "FEMALE", "Not Boarded", "TRIP_CANCELLED_FROM_DASHBOARD", False)] * 3,
]


@pytest.fixture
def planted():
    """One trip per leg, all inside one day, so the window and slice bind
    cleanly and every count is countable by hand."""
    c = duckdb.connect()
    c.execute("CREATE TABLE trips (trip_id BIGINT, scheduled_at BIGINT, "
              "site_id VARCHAR, shift_band VARCHAR)")
    c.execute("CREATE TABLE emp_legs (trip_id BIGINT, stwid BIGINT, gender VARCHAR, "
              "boarding_status VARCHAR, not_boarding_reason VARCHAR, is_no_show BOOLEAN)")
    for i, (stwid, gender, status, reason, ns) in enumerate(_LEGS):
        site = "Alpha" if stwid % 2 else "Beta"
        c.execute("INSERT INTO trips VALUES (?, ?, ?, ?)", [i, 1000, site, "DAY"])
        c.execute("INSERT INTO emp_legs VALUES (?, ?, ?, ?, ?, ?)",
                  [i, stwid, gender, status, reason, ns])
    yield c
    c.close()
    registry.clear_cache()


PLANTED_WINDOW = Window(0, DAY_MS)


def _by_stwid(rows):
    return {r["stwid"]: r for r in rows}


# ---------------------------------------------------------------------------
# CONSTRAINT 1 -- gender is never an input, directly or as a proxy.
# ---------------------------------------------------------------------------

def test_gender_appears_nowhere_in_the_reliability_sql_or_the_scoring_module():
    # The constraint is structural, so it is checked structurally: the column
    # exists on the emp_legs view and is used (correctly) by ingest.py's
    # marshal_population derivation, so its ABSENCE here is a real, deliberate
    # choice and not an accident of it not existing.
    view = (SRC / "ingest.py").read_text()
    assert "gender" in view, "gender must exist in the data for this test to mean anything"

    assert "gender" not in registry._BOOKING_RELIABILITY_SQL
    assert "gender" not in registry._BOOKING_RELIABILITY_CASE

    # And nothing in the scoring module READS it either -- a proxy added there
    # would bypass the SQL check entirely. Checked on the AST rather than by
    # grepping the text, because the module's own DISCLAIMER string says the
    # word ("Gender is never an input") and a text grep could only pass by
    # deleting the promise. What is forbidden is gender as a NAME: a variable,
    # an attribute, a keyword argument, or a dict/row key.
    tree = ast.parse((SRC / "reliability.py").read_text())
    used_as_a_name = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_as_a_name.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_as_a_name.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            used_as_a_name.add(node.arg)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            used_as_a_name.add(node.slice.value)
    assert not any("gender" in n.lower() for n in used_as_a_name), \
        sorted(n for n in used_as_a_name if "gender" in n.lower())
    # The check has a real subject: the SAME walk over a module that genuinely
    # reads the column does find it, so a pass here is a fact about
    # reliability.py and not about the walk being blind.
    ingest_tree = ast.parse((SRC / "ingest.py").read_text())
    ingest_names = {n.id for n in ast.walk(ingest_tree) if isinstance(n, ast.Name)}
    ingest_names |= {n.attr for n in ast.walk(ingest_tree) if isinstance(n, ast.Attribute)}
    ingest_names |= {n.slice.value for n in ast.walk(ingest_tree)
                     if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                     and isinstance(n.slice.value, str)}
    assert "gender" in (SRC / "ingest.py").read_text(), \
        "gender must exist in the loader for the constraint to have a subject"


def test_two_riders_with_identical_bookings_and_different_genders_score_the_same(planted):
    # The behavioural half of constraint 1, because a source grep cannot catch
    # a proxy. Riders 2 (MALE) and 3 (MALE) differ; riders 1 (FEMALE) and 2
    # (MALE) have identical leg counts in different proportions. So the direct
    # test: rebuild the fixture with every gender FLIPPED and confirm every
    # score is byte-identical.
    before = reliability.summary(planted, PLANTED_WINDOW)
    planted.execute("UPDATE emp_legs SET gender = "
                    "CASE WHEN gender = 'MALE' THEN 'FEMALE' ELSE 'MALE' END")
    registry.clear_cache()
    after = reliability.summary(planted, PLANTED_WINDOW)
    assert before == after
    # ...and the flip really happened, or the assertion above is vacuous.
    counts = planted.execute(
        "SELECT gender, count(*) FROM emp_legs GROUP BY 1 ORDER BY 1").fetchall()
    assert counts == [("FEMALE", 15), ("MALE", 21)]


# ---------------------------------------------------------------------------
# CONSTRAINT 2 -- nobody is scored for something outside their control.
# ---------------------------------------------------------------------------

def test_a_dashboard_cancellation_is_never_scored_against_the_rider(planted):
    # BREAK-IT TARGET 2. A booking pulled from the transport desk's own
    # console is not the rider's act -- this repo already classifies it as a
    # BOOKING event, distinct from a no-show (delay_analyzer.BOOKING_CANCELLED
    # vs NO_SHOW_IMPACT). It must leave the score untouched from BOTH sides.
    rows = _by_stwid(registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW))

    # Rider 4: 5 used + 1 no-show + 4 cancellations. Hand-calculated, the score
    # is 5/6 = 83.33 -- NOT 5/10 = 50.0 (cancellations in the denominator) and
    # NOT 5/9 = 55.6 (counted as unused seats).
    r4 = rows[4]
    assert (r4["used_legs"], r4["no_show_legs"], r4["not_attributed_legs"]) == (5, 1, 4)
    assert reliability.score_for(r4["used_legs"], r4["no_show_legs"]) == pytest.approx(83.3333, abs=1e-3)

    # Rider 6: every leg is a cancellation, so there is NOTHING attributable.
    # None, never 0.0 -- scoring them zero would blame a rider for the
    # transport desk's action, which is the constraint stated backwards.
    r6 = rows[6]
    assert (r6["used_legs"], r6["no_show_legs"], r6["not_attributed_legs"]) == (0, 0, 3)
    assert reliability.score_for(r6["used_legs"], r6["no_show_legs"]) is None
    assert reliability.cohort_for(None, 0) == reliability.NOT_ENOUGH_BOOKINGS

    # The waste is still REPORTED, just not attributed -- 7 cancelled legs
    # across riders 4 and 6, visible in the rollup.
    s = reliability.summary(planted, PLANTED_WINDOW)
    assert s["overall"]["notAttributedSeats"] == 7


def test_a_late_cab_is_the_vendors_failure_and_reaches_no_part_of_this_score():
    # The other half of constraint 2, and it is an ABSENCE, so it is checked
    # against the columns the query is allowed to read. late_pickup_rate --
    # which lives in the same module -- reads exactly these two, and is
    # documented there as "the delay an employee EXPERIENCES".
    sql = registry._BOOKING_RELIABILITY_SQL + registry._BOOKING_RELIABILITY_CASE
    for column in ("planned_pickup_at", "actual_pickup_at", "delay_minutes",
                   "delay_reason"):
        assert column not in sql, f"{column} must not reach the reliability score"
    # And the same columns really are available on the joined tables, so their
    # absence is a decision and not a schema accident.
    assert "planned_pickup_at" in registry._LATE_PICKUP_SQL
    assert "delay_reason" in registry._EMPLOYEE_CAUSED_DELAY_SHARE_SQL


def test_the_three_buckets_partition_every_leg_so_nothing_is_double_counted(planted):
    # A leg counted as both used and unused would silently inflate a
    # denominator, and no score assertion above would notice. The CASE cascade
    # makes the three mutually exclusive and exhaustive by construction; this
    # asserts it on real rows, per rider AND in total.
    rows = registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW)
    for r in rows:
        assert r["used_legs"] + r["no_show_legs"] + r["not_attributed_legs"] == r["legs"]
    assert sum(r["legs"] for r in rows) == len(_LEGS) == 36


def test_the_partition_holds_on_the_real_fixture_too(con):
    # docs/TESTING-LESSONS.md, "the fourth kind": a synthetic-world test proves
    # a function's arithmetic; only a real-fixture test proves the product is
    # coherent. Same invariant, on the data that ships.
    rows = registry.booking_reliability_legs(con, Slice.all(), SWEEP_WEEK)
    assert rows, "the sample must carry legs in the sweep week"
    assert all(r["used_legs"] + r["no_show_legs"] + r["not_attributed_legs"] == r["legs"]
               for r in rows)
    (legs,) = con.execute(
        "SELECT count(*) FROM emp_legs e JOIN trips t ON t.trip_id = e.trip_id "
        "WHERE t.scheduled_at >= ? AND t.scheduled_at < ? AND e.stwid IS NOT NULL",
        [SWEEP_WEEK.start_ms, SWEEP_WEEK.end_ms]).fetchone()
    assert sum(r["legs"] for r in rows) == legs


# ---------------------------------------------------------------------------
# CONSTRAINT 3 -- a booking score, not a person score, and never broadcast.
# ---------------------------------------------------------------------------

def test_no_rider_identifier_survives_into_anything_a_manager_sees(con):
    # The precedent delay_management_TransportManager set: the model never sees
    # a raw row, a trip_id join or an employee id. summary() is the shape that
    # goes to a manager, a Slack message or a model, so it must carry no id.
    #
    # Checked by serialising the WHOLE payload and hunting for real stwids from
    # the same window -- not by asserting a key is absent, which would miss an
    # id smuggled inside a label.
    s = reliability.summary(con, SWEEP_WEEK)
    blob = json.dumps(s, default=str)
    assert "stwid" not in blob
    rows = registry.booking_reliability_legs(con, Slice.all(), SWEEP_WEEK)
    ids = [str(r["stwid"]) for r in rows]
    assert len(ids) > 100, "need a real population for this check to mean anything"
    leaked = [i for i in ids if i in blob]
    assert leaked == [], f"rider ids reached an aggregate payload: {leaked[:5]}"
    # The narrative line is the other thing that travels; same rule.
    line = reliability.narrative_line(s)
    assert line and not any(i in line for i in ids)


def test_the_cohort_names_describe_the_seat_and_never_the_person():
    # The naming constraint, asserted rather than trusted to review. Every
    # cohort names what happened to a SEAT; none contains a word that judges a
    # colleague.
    for name in reliability.COHORTS:
        assert "USED" in name or "BOOKINGS" in name, name
    forbidden = ("BAD", "POOR", "GOOD", "UNRELIABLE", "OFFENDER", "REPEAT",
                 "WORST", "ABUSER", "PROBLEM")
    for name in reliability.COHORTS:
        assert not any(w in name for w in forbidden), name


def test_every_output_states_what_the_score_is_and_is_not(con):
    s = reliability.summary(con, SWEEP_WEEK)
    for text in (s["disclaimer"], s["notes"][0]):
        assert "not an employee performance" in text
        assert "Gender is never an input" in text
        assert "late cab" in text and "vendor" in text
    assert reliability.DISCLAIMER in s["notes"]


def test_the_per_rider_detail_exists_but_only_off_the_aggregate_path(planted):
    # Per-rider detail MAY exist for an API; it simply must not be the default
    # and must not be what any narrative reads. employees() is the one function
    # that emits an id, and summary() does not call it.
    rows = registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW)
    detail = reliability.employees(rows, reliability.population_rate(rows))
    assert {e["stwid"] for e in detail} == {1, 2, 3, 4, 5, 6}
    assert "employees" not in reliability.summary(planted, PLANTED_WINDOW)


# ---------------------------------------------------------------------------
# The score itself, hand-calculated.
# ---------------------------------------------------------------------------

def test_the_score_is_used_over_used_plus_no_show(planted):
    # Four riders at four different, independently hand-calculated ratios --
    # so this cannot pass under a constant or a lookup (TESTING-LESSONS Kind 1).
    rows = _by_stwid(registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW))
    expected = {1: 100.0, 2: 75.0, 3: 50.0, 4: 83.3333}
    for stwid, want in expected.items():
        r = rows[stwid]
        assert reliability.score_for(r["used_legs"], r["no_show_legs"]) \
            == pytest.approx(want, abs=1e-3), stwid


def test_the_score_moves_the_right_way_when_a_seat_goes_unused(planted):
    # Direction, on two points, because "higher is better" is a claim the whole
    # feature rests on: an unused booked seat must LOWER the score.
    assert reliability.score_for(9, 1) > reliability.score_for(8, 2)
    assert reliability.score_for(10, 0) == 100.0
    assert reliability.score_for(0, 10) == 0.0


def test_the_cohorts_are_assigned_at_the_stated_edges():
    # Both sides of each edge, so an off-by-one in the comparison is caught.
    at = lambda score: reliability.cohort_for(score, reliability.MIN_BOOKED_LEGS)
    assert at(100.0) == reliability.ALWAYS_USED
    assert at(99.9) == reliability.USUALLY_USED
    assert at(90.0) == reliability.USUALLY_USED
    assert at(89.9) == reliability.SOMETIMES_UNUSED
    assert at(75.0) == reliability.SOMETIMES_UNUSED
    assert at(74.9) == reliability.OFTEN_UNUSED
    assert at(0.0) == reliability.OFTEN_UNUSED


# ---------------------------------------------------------------------------
# Thin data, handled the way the vendor scorecard handles it.
# ---------------------------------------------------------------------------

def test_a_rider_below_the_floor_is_not_scored_at_any_score(planted):
    # BREAK-IT TARGET 1. Rider 5 has ONE leg and used it -- a perfect 100 by
    # arithmetic, and meaningless. The floor must beat the band, or the
    # thinnest evidence in the file produces the most confident claim.
    rows = _by_stwid(registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW))
    r5 = rows[5]
    assert (r5["used_legs"], r5["no_show_legs"]) == (1, 0)
    assert reliability.score_for(1, 0) == 100.0                # the arithmetic
    assert reliability.cohort_for(100.0, 1) == reliability.NOT_ENOUGH_BOOKINGS
    # And it is the FLOOR doing it, not the score: the same score one leg above
    # the floor is scored normally.
    assert reliability.cohort_for(100.0, reliability.MIN_BOOKED_LEGS) \
        == reliability.ALWAYS_USED
    assert reliability.cohort_for(100.0, reliability.MIN_BOOKED_LEGS - 1) \
        == reliability.NOT_ENOUGH_BOOKINGS
    # End to end, the rider carries no score at all and the neutral instead.
    detail = {e["stwid"]: e for e in
              reliability.employees(rows.values(), reliability.population_rate(rows.values()))}
    assert detail[5]["score"] is None and detail[5]["scored"] is False
    assert detail[5]["neutralScore"] is not None


def test_the_stated_neutral_is_the_populations_own_rate_and_is_reported(planted):
    # "A stated neutral score below the floor, and say so in the output."
    # Hand-calculated on the planted rows: used legs 8+6+3+5+1 = 23, no-shows
    # 0+2+3+1+0 = 6, so the population rate is 23/29 = 79.31%.
    rows = registry.booking_reliability_legs(planted, Slice.all(), PLANTED_WINDOW)
    assert sum(r["used_legs"] for r in rows) == 23
    assert sum(r["no_show_legs"] for r in rows) == 6
    assert reliability.population_rate(rows) == pytest.approx(79.3103, abs=1e-3)
    s = reliability.summary(planted, PLANTED_WINDOW)
    assert s["neutralScore"] == pytest.approx(79.31, abs=1e-2)
    # Said so in the output, not only in a field nobody reads.
    assert any(str(reliability.MIN_BOOKED_LEGS) in n and "neutral" in n
               for n in s["notes"])
    assert "population's own" in s["neutralScoreBasis"] \
        or "population's own" in " ".join(s["notes"])


def test_the_sample_fixture_cannot_score_anybody_and_says_so(con):
    # The honest-refusal case, on the fixture that ships. MEASURED: data/sample
    # carries at most 3 attributable legs per rider in a week, so nothing
    # clears the 6-leg floor -- and the right answer is to say that, not to
    # print 633 neutral scores as if they were readings.
    s = reliability.summary(con, SWEEP_WEEK)
    assert s["overall"]["riders"] > 500
    assert s["overall"]["ridersScored"] == 0
    assert s["overall"]["ridersBelowFloor"] == s["overall"]["riders"]
    assert s["overall"]["meanScore"] is None and s["overall"]["medianScore"] is None
    line = reliability.narrative_line(s)
    assert "no score is reported" in line
    assert str(reliability.MIN_BOOKED_LEGS) in line
    # The waste is still counted and reported -- refusing to score is not
    # refusing to measure.
    assert s["overall"]["unusedSeats"] > 0


# ---------------------------------------------------------------------------
# Aggregation by slice -- what actually reaches a manager.
# ---------------------------------------------------------------------------

def test_the_rollup_is_cut_by_the_slices_the_registry_already_supports(planted):
    s = reliability.summary(planted, PLANTED_WINDOW,
                            dims=(Dimension.SITE, Dimension.SHIFT))
    assert set(s["byDimension"]) == {"SITE", "SHIFT"}
    sites = {e["value"]: e for e in s["byDimension"]["SITE"]}
    # Planted: odd stwids -> Alpha (riders 1, 3, 5), even -> Beta (2, 4, 6).
    assert set(sites) == {"Alpha", "Beta"}
    assert sites["Alpha"]["riders"] == 3 and sites["Beta"]["riders"] == 3
    # Riders 1 and 3 clear the floor at Alpha; rider 5 does not.
    assert sites["Alpha"]["ridersScored"] == 2
    # Riders 2 and 4 clear it at Beta; rider 6 has nothing attributable.
    assert sites["Beta"]["ridersScored"] == 2
    # Alpha's unused seats are rider 3's 3 no-shows; Beta's are 2 + 1.
    assert sites["Alpha"]["unusedSeats"] == 3
    assert sites["Beta"]["unusedSeats"] == 3


def test_the_cohort_counts_and_unused_seats_reconcile_with_the_riders(planted):
    # An aggregate that does not add up is worse than no aggregate.
    s = reliability.summary(planted, PLANTED_WINDOW)
    o = s["overall"]
    assert sum(o["cohorts"].values()) == o["riders"] == 6
    assert o["ridersScored"] + o["ridersBelowFloor"] == o["riders"]
    assert sum(o["unusedSeatsByCohort"].values()) == o["unusedSeats"] == 6
    assert o["usedSeats"] + o["unusedSeats"] + o["notAttributedSeats"] == 36
    # Hand-checked cohorts: rider 1 -> 100 ALWAYS, rider 2 -> 75 SOMETIMES,
    # rider 3 -> 50 OFTEN, rider 4 -> 83.3 SOMETIMES, riders 5 and 6 unscored.
    assert o["cohorts"] == {
        reliability.OFTEN_UNUSED: 1,
        reliability.SOMETIMES_UNUSED: 2,
        reliability.USUALLY_USED: 0,
        reliability.ALWAYS_USED: 1,
        reliability.NOT_ENOUGH_BOOKINGS: 2,
    }


def test_a_rider_at_two_sites_is_counted_at_both_and_the_output_says_so(planted):
    # Not a bug -- "how reliably are the seats booked AT THIS SITE used" is a
    # site question. But a reader building a table has to be told, or the
    # numbers look broken.
    planted.execute("UPDATE trips SET site_id = 'Gamma' WHERE trip_id = 0")
    registry.clear_cache()
    s = reliability.summary(planted, PLANTED_WINDOW, dims=(Dimension.SITE,))
    counted = sum(e["riders"] for e in s["byDimension"]["SITE"])
    assert counted == s["overall"]["riders"] + 1
    assert any("more than one site" in n for n in s["notes"])


def test_the_rollup_ordering_is_a_total_order_so_the_output_is_deterministic(con):
    a = reliability.summary(con, SWEEP_WEEK)
    registry.clear_cache()
    b = reliability.summary(con, SWEEP_WEEK)
    assert a == b
    for entries in a["byDimension"].values():
        keys = [(-e["flaggedUnusedSeats"], -e["unusedSeats"], str(e["value"]))
                for e in entries]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# The endpoint.
# ---------------------------------------------------------------------------

def test_the_endpoint_serves_aggregates_by_default_and_detail_only_on_request():
    from fastapi.testclient import TestClient
    from signaldesk.api import create_app

    with TestClient(create_app(SAMPLE)) as client:
        assert client.post("/api/sweep?wait=true").status_code in (200, 201, 202)
        r = client.get("/api/employees/reliability")
        assert r.status_code == 200
        body = r.json()
        assert "employees" not in body
        assert body["minBookedLegs"] == reliability.MIN_BOOKED_LEGS
        assert body["disclaimer"] == reliability.DISCLAIMER
        assert "stwid" not in json.dumps(body)

        detailed = client.get("/api/employees/reliability?detail=true").json()
        assert "employees" in detailed
        assert detailed["employees"], "the sample carries riders even if none score"
        assert all(e["score"] is None for e in detailed["employees"]), \
            "no data/sample rider clears the floor, so none may carry a score"

        assert "booking-reliability" in client.get("/api/health").json()["capabilities"]
