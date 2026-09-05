"""forecast.py -- Task 14's shift readiness outlook.

The point of this file is that the outlook is a STATED SEASONAL BASELINE and
not a model: the weighted mean is the arithmetic the module constant declares,
the interval is the spread of the four basis days THEMSELVES, and fewer than
four basis days degrades or refuses rather than silently averaging fewer.

Every expected value below is HAND-CALCULATED and written as a literal --
never recomputed by the test with the same expression the implementation uses
(docs/TESTING-LESSONS.md: a test that recomputes the behaviour it names
asserts nothing).
"""
from __future__ import annotations

import datetime as dt
import math

import duckdb
import pytest

from signaldesk import forecast, ingest, registry
from signaldesk.schemas import Dimension, Metric, Slice, Tier, Window

DAY_MS = 86_400_000


def _ms(y, m, d) -> int:
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


# Wednesday. Its four same-weekday basis days are 2026-07-22, 07-15, 07-08,
# 07-01 -- checked below, not assumed.
TARGET = _ms(2026, 7, 29)


# ---------------------------------------------------------------------------
# The arithmetic, in isolation. Hand-calculated literals.
# ---------------------------------------------------------------------------

def test_weighted_mean_is_the_declared_recency_ramp():
    # 4*10 + 3*20 + 2*30 + 1*40 = 40 + 60 + 60 + 40 = 200; 200/10 = 20.0
    assert forecast.weighted_mean([10.0, 20.0, 30.0, 40.0], [4.0, 3.0, 2.0, 1.0]) == 20.0


def test_weights_are_the_module_constant_and_favour_recency():
    assert forecast.WEIGHTS == (4, 3, 2, 1)
    # A plain mean of these four is 25.0; the recency ramp must NOT return it,
    # or the declared weighting is not being applied at all.
    assert forecast.weighted_mean([10.0, 20.0, 30.0, 40.0],
                                  list(map(float, forecast.WEIGHTS))) != 25.0


def test_weighted_mean_refuses_an_empty_basis_rather_than_returning_zero():
    with pytest.raises(ValueError):
        forecast.weighted_mean([], [])


def test_spread_is_the_population_sd_of_the_observations_themselves():
    # mean(2,4,4,4) = 3.5; deviations -1.5, 0.5, 0.5, 0.5; squares 2.25, .25,
    # .25, .25 -> sum 3.0; 3.0/4 = 0.75; sqrt(0.75) = 0.8660254037844386
    assert forecast.spread([2.0, 4.0, 4.0, 4.0]) == pytest.approx(0.8660254037844386, abs=1e-12)


def test_spread_of_a_single_observation_is_zero():
    assert forecast.spread([7.0]) == 0.0


# ---------------------------------------------------------------------------
# project() over a stubbed registry, so the basis values are known exactly and
# the expected projection can be written down by hand.
# ---------------------------------------------------------------------------

_METRIC = registry.by_id("no_show_rate")


class _StubRegistry:
    """Stands in for registry.evaluate/evidence_sql/planned_seats, keyed by the
    basis day's start_ms so each of the four weeks can be given its own value
    (or None, to force degradation)."""

    def __init__(self, by_start: dict[int, float | None], seats: dict[int, int] | None = None):
        self.by_start = by_start
        self.seats = seats or {}

    def evaluate(self, con, metric, slc, window):
        return self.by_start.get(window.start_ms)

    def evidence_sql(self, metric, slc, window):
        return f"-- SQL for {metric.id} over {window.start_ms}..{window.end_ms}"

    def planned_seats(self, con, slc, window):
        return self.seats.get(window.start_ms, 0)


@pytest.fixture
def stub(monkeypatch):
    """Install a stub registry into forecast's namespace and a no-reference
    readiness, so a test can pin the arithmetic without a database."""
    def install(by_start, seats=None, tier=None, reference=None):
        st = _StubRegistry(by_start, seats)
        monkeypatch.setattr(forecast.registry, "evaluate", st.evaluate)
        monkeypatch.setattr(forecast.registry, "evidence_sql", st.evidence_sql)
        monkeypatch.setattr(forecast.registry, "planned_seats", st.planned_seats)
        monkeypatch.setattr(forecast, "_readiness",
                            lambda con, metric, slc, projected, target: (tier, reference))
        return st
    return install


def _basis_starts(target=TARGET):
    return [target - w * 7 * DAY_MS for w in (1, 2, 3, 4)]


def test_basis_days_are_the_same_weekday_from_the_last_four_weeks(stub):
    stub({s: 1.0 for s in _basis_starts()})
    basis = forecast.basis_days(None, _METRIC, Slice.all(), TARGET)
    assert [b.date for b in basis] == ["2026-07-22", "2026-07-15", "2026-07-08", "2026-07-01"]
    assert {b.weekday for b in basis} == {"Wednesday"}
    assert [b.weeks_back for b in basis] == [1, 2, 3, 4]
    assert [b.weight for b in basis] == [4, 3, 2, 1]
    # Every basis observation carries the SQL that produced it: the whole
    # point of "not a model" is that a judge can run these four queries.
    assert all(b.sql for b in basis)


def test_projection_is_the_hand_calculated_weighted_mean(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s1: 10.0, s2: 20.0, s3: 30.0, s4: 40.0})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    # (4*10 + 3*20 + 2*30 + 1*40) / 10 = 200/10 = 20.0, computed by hand.
    assert p.projected == pytest.approx(20.0, abs=1e-9)
    assert p.basis_days_used == 4
    assert p.degraded is False
    assert p.withheld is False
    assert p.method == "seasonal-baseline-4w"


def test_interval_is_one_sd_of_the_basis_observations_not_a_modelled_variance(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s1: 10.0, s2: 20.0, s3: 30.0, s4: 40.0})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    # mean(10,20,30,40) = 25; deviations -15,-5,5,15; squares 225,25,25,225 ->
    # 500; 500/4 = 125; sqrt(125) = 11.180339887498949. Note this is the sd
    # around the PLAIN mean of the four observations (25), NOT around the
    # weighted projection (20) -- the spread of the basis days themselves.
    assert p.interval_low == pytest.approx(20.0 - 11.180339887498949, abs=1e-9)
    assert p.interval_high == pytest.approx(20.0 + 11.180339887498949, abs=1e-9)


def test_four_identical_basis_days_give_a_zero_width_interval(stub):
    stub({s: 12.5 for s in _basis_starts()})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert p.projected == pytest.approx(12.5)
    assert p.interval_low == pytest.approx(12.5)
    assert p.interval_high == pytest.approx(12.5)


def test_three_basis_days_degrades_and_says_so_rather_than_averaging_silently(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s1: 10.0, s2: 20.0, s3: 30.0, s4: None})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert p.degraded is True
    assert p.withheld is False
    assert p.basis_days_used == 3
    # (4*10 + 3*20 + 2*30) / 9 = 160/9 = 17.77777... by hand.
    assert p.projected == pytest.approx(17.77777777777778, abs=1e-9)
    # sd of (10,20,30) around their plain mean 20: squares 100,0,100 -> 200/3
    # -> sqrt = 8.16496580927726, WIDENED 2x = 16.32993161855452.
    assert (p.interval_high - p.projected) == pytest.approx(16.32993161855452, abs=1e-9)
    # The response SAYS it degraded -- a silent narrower average is the bug
    # this whole branch exists to prevent.
    assert "3 of 4" in p.note
    assert "2026-07-01" in p.note          # the missing day is named
    assert "widened" in p.note.lower()


def test_one_basis_day_is_withheld_not_projected(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s1: 10.0, s2: None, s3: None, s4: None})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert p.withheld is True
    assert p.projected is None
    assert p.interval_low is None and p.interval_high is None
    assert p.readiness == forecast.READINESS_WITHHELD
    assert "Withheld" in p.note
    # A stated refusal, not a confident number: the action must say why.
    assert "1 of 4" in p.action
    assert p.basis_days_used == 1


def test_no_basis_day_at_all_is_withheld(stub):
    stub({})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert p.withheld is True and p.projected is None


def test_two_basis_days_is_the_lowest_that_still_projects(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s1: 10.0, s2: 20.0, s3: None, s4: None})
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert forecast.MIN_BASIS_DAYS == 2
    assert p.withheld is False and p.degraded is True
    # (4*10 + 3*20) / 7 = 100/7 = 14.285714285714286 by hand.
    assert p.projected == pytest.approx(14.285714285714286, abs=1e-9)


# ---------------------------------------------------------------------------
# The readiness label reuses the EXISTING bands -- there is no second scale.
# ---------------------------------------------------------------------------

def test_readiness_label_is_one_to_one_with_the_existing_tiers():
    assert set(forecast.READINESS_BY_TIER) == set(Tier)
    assert len(set(forecast.READINESS_BY_TIER.values())) == len(Tier)


@pytest.mark.parametrize("tier,label", [
    (Tier.PASS, "READY"), (Tier.WATCH, "WATCH"),
    (Tier.CONCERN, "AT_RISK"), (Tier.BREACH, "NOT_READY"),
])
def test_readiness_label_matches_the_tier_the_bands_produce(stub, tier, label):
    stub({s: 10.0 for s in _basis_starts()}, tier=tier)
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert p.tier is tier
    assert p.readiness == label


def test_readiness_comes_from_constants_BANDS_via_verdict_not_a_new_scale():
    """_readiness must tier the projection through verdict.tier_for over the
    metric's own references -- so the bands in constants.py are the only
    scale in the product. Checked against a real connection below in the
    integration tests; here, that the projection lands where tier_for says.
    """
    from signaldesk import constants as C, verdict
    from signaldesk.schemas import Direction
    # HIGHER-is-better, PASS band 0.05: a projection 1% below its reference
    # (delta 0.01) is PASS; 30% below (delta 0.30) is CONCERN under
    # (0.05, 0.20, 0.75).
    assert C.BANDS["HIGHER"] == (0.05, 0.20, 0.75)
    assert verdict.tier_for(0.01, False, Direction.HIGHER) is Tier.PASS
    assert verdict.tier_for(0.30, False, Direction.HIGHER) is Tier.CONCERN
    assert forecast.READINESS_BY_TIER[Tier.CONCERN] == "AT_RISK"


# ---------------------------------------------------------------------------
# The no_show_rate action names a SEAT COUNT, via registry.planned_seats.
# ---------------------------------------------------------------------------

def test_no_show_action_names_a_seat_count_from_planned_seats(stub):
    s1, s2, s3, s4 = _basis_starts()
    # A flat 10% no-show rate over a flat 1,000 planned seats a day, so the
    # weighted mean of both is exactly the flat value and the seat arithmetic
    # can be written down: 10% of 1,000 = 100 seats.
    stub({s1: 10.0, s2: 10.0, s3: 10.0, s4: 10.0},
         seats={s: 1000 for s in (s1, s2, s3, s4)}, tier=Tier.CONCERN)
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert "100 of the ~1000 planned seats" in p.action
    assert "Release" in p.action


def test_no_show_action_names_a_seat_count_even_at_ready(stub):
    # A rate alone is not something a facilities head can release -- the seat
    # count is named at every readiness level, not only a bad one.
    s1, s2, s3, s4 = _basis_starts()
    stub({s: 5.0 for s in (s1, s2, s3, s4)},
         seats={s: 200 for s in (s1, s2, s3, s4)}, tier=Tier.PASS)
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    assert "10 of the ~200 planned seats" in p.action


def test_no_show_seat_count_weights_planned_seats_the_same_way_as_the_rate(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s: 10.0 for s in (s1, s2, s3, s4)},
         seats={s1: 1000, s2: 500, s3: 500, s4: 500}, tier=Tier.CONCERN)
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    # (4*1000 + 3*500 + 2*500 + 1*500) / 10 = (4000+1500+1000+500)/10 = 700.
    # 10% of 700 = 70 seats. Both halves of the sentence come from one method.
    assert "70 of the ~700 planned seats" in p.action


def test_a_non_no_show_metric_does_not_claim_a_seat_count(stub):
    s1, s2, s3, s4 = _basis_starts()
    stub({s: 50.0 for s in (s1, s2, s3, s4)}, tier=Tier.CONCERN)
    p = forecast.project(None, registry.by_id("ota"), Slice.all(), TARGET)
    assert "planned seats" not in p.action
    assert "on-time arrival" in p.action.lower()


# ---------------------------------------------------------------------------
# Never a forecast, never a prediction. This is the wording bar the plan sets.
# ---------------------------------------------------------------------------

def test_no_projection_ever_calls_itself_a_forecast_or_a_prediction(stub):
    stub({s: 10.0 for s in _basis_starts()},
         seats={s: 100 for s in _basis_starts()}, tier=Tier.CONCERN)
    p = forecast.project(None, _METRIC, Slice.all(), TARGET)
    text = " ".join([p.action, p.note]).lower()
    assert "predict" not in text
    # "forecast" may appear ONLY as an explicit denial ("not a forecast") --
    # every occurrence, not merely one of them.
    assert text.count("forecast") == text.count("not a forecast")


# ---------------------------------------------------------------------------
# Against the real sample database: the basis SQL actually runs, and the
# numbers the API would serve are reproducible from those four queries.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def con():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    c = duckdb.connect()
    ingest.load_all(c, ingest.source_for(str(root / "data" / "sample")))
    registry.clear_cache()
    yield c
    c.close()


def test_every_basis_sql_is_runnable_and_returns_the_reported_value(con):
    p = forecast.project(con, registry.by_id("ota"), Slice.all(), TARGET)
    assert p.basis_days_used == 4, "sample data should carry four Wednesdays here"
    for b in p.basis:
        row = con.execute(b.sql).fetchone()
        assert row is not None and row[0] is not None
        # The value the projection averaged IS what the attached query returns.
        assert float(row[0]) == pytest.approx(b.value, abs=1e-6)


def test_projection_reproduces_by_hand_from_its_own_basis_values(con):
    p = forecast.project(con, registry.by_id("ota"), Slice.all(), TARGET)
    v = [b.value for b in p.basis]
    expected = (4 * v[0] + 3 * v[1] + 2 * v[2] + 1 * v[3]) / 10.0
    assert p.projected == pytest.approx(expected, abs=1e-9)
    mean = sum(v) / 4
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / 4)
    assert p.interval_high - p.projected == pytest.approx(sd, abs=1e-9)


def test_shift_outlook_covers_the_shift_bands_the_data_carries(con):
    window = Window(TARGET - 7 * DAY_MS, TARGET)
    bands = set(registry.distinct_values(con, Dimension.SHIFT, window))
    out = forecast.shift_outlook(con, TARGET)
    assert {p.slice_label.replace("shift ", "") for p in out} == bands
    assert all(p.method == "seasonal-baseline-4w" for p in out)


def test_outlook_line_names_the_method_as_a_baseline_not_a_forecast(con):
    from signaldesk.sweep import sweep
    from signaldesk.schemas import FeedHealth

    class _Clock:
        def millis(self):
            return TARGET

    health = {f: FeedHealth.of(f, 100, 0, 0, 0) for f in ("trips", "bill", "emp_legs")}
    run = sweep(con, _Clock(), health)
    line = forecast.outlook_line(con, run)
    assert line is not None and line.startswith("outlook:")
    assert "baseline" in line
    low = line.lower()
    assert "predict" not in low
    # Names the method as a baseline; the word "forecast" only ever as a denial.
    assert low.count("forecast") == low.count("not a forecast")
    assert "not a forecast" in low


def test_outlook_line_carries_a_real_projection_when_one_can_be_built(con):
    """The brief line must be a NUMBER when a baseline exists, not always a
    refusal: outlook_line walks the ranked findings for the worst one whose
    own metric x slice has same-weekday history."""
    from signaldesk.sweep import sweep
    from signaldesk.schemas import FeedHealth

    class _Clock:
        def millis(self):
            return TARGET

    health = {f: FeedHealth.of(f, 100, 0, 0, 0) for f in ("trips", "bill", "emp_legs")}
    run = sweep(con, _Clock(), health)
    line = forecast.outlook_line(con, run)
    assert "at about" in line, line
    assert any(ch.isdigit() for ch in line)
