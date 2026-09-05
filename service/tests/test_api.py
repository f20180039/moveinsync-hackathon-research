"""api.py: the HTTP contract the console, delivery and the interrogator are
written against. GET /api/runs/{id}/findings is a FROZEN contract (Controller
ruling, task-5) -- checked here against handoff/fake-findings.json's key set,
not just "some JSON came back".

One module-scoped app/TestClient (startup pointed at data/sample) so the whole
file stays well under the ~20s budget: a fresh DuckDB load per test would blow
that on its own.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from signaldesk import registry, tools
from signaldesk.api import create_app, finding_to_json
from signaldesk.sweep import STORE

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE = str(ROOT / "data" / "sample")
FIXTURE = json.loads((ROOT / "handoff" / "fake-findings.json").read_text())


@pytest.fixture(scope="module")
def client():
    app = create_app(data_dir=SAMPLE)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/health -- ok after startup's unprompted sweep.
# ---------------------------------------------------------------------------

def test_health_is_ok_after_startup(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Task 11 activated cost_per_km/marshal_compliance; Task 15 adds
    # late_pickup_rate/cost_per_rider -- 8 active metrics now.
    assert set(body["activeMetrics"]) == {
        "ota", "otd", "vendor_ota", "no_show_rate", "cost_per_km",
        "marshal_compliance", "late_pickup_rate", "cost_per_rider"}
    assert isinstance(body["clock"], int)


# ---------------------------------------------------------------------------
# GET /api/health -- capabilities, so the console feature-detects without
# probing /api/ask with an empty question (which is correctly a 422, and
# which the console read as "endpoint absent" -- disabling the assistant
# against a fully working backend).
# ---------------------------------------------------------------------------

def test_health_advertises_ask_capability(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "ask" in r.json()["capabilities"]


def test_health_capabilities_name_every_optional_endpoint_served(client):
    # Exact set, not a subset: deleting one of these routes drops its name
    # from the derived list and fails here, rather than leaving the console
    # feature-detecting an endpoint that no longer exists.
    # Task 14 adds "outlook" to the same list -- additive, and the six names
    # the console was written against are unchanged.
    assert set(client.get("/api/health").json()["capabilities"]) == {
        "ask", "decompose", "safety", "employees", "cost", "dispatch-log",
        "outlook"}


def test_health_capabilities_are_all_really_routed(client):
    # Every advertised name must correspond to a route that answers something
    # other than 404-not-routed. The console trusts this list.
    caps = client.get("/api/health").json()["capabilities"]
    probes = {
        "ask": client.post("/api/ask", json={"question": "how is on-time?"}),
        "decompose": client.get("/api/findings/nope/decompose"),
        "safety": client.get("/api/runs/latest/safety"),
        "employees": client.get("/api/employees/impact"),
        "cost": client.get("/api/cost"),
        "dispatch-log": client.get("/api/dispatch/log"),
        "outlook": client.get("/api/outlook"),
    }
    for name in caps:
        assert probes[name].status_code != 405
        assert probes[name].json() != {"detail": "Not Found"}


def test_health_keeps_its_pre_existing_fields(client):
    # The console's Data health panel reads these; capabilities is additive.
    body = client.get("/api/health").json()
    assert {"status", "activeMetrics", "clock", "capabilities"} <= set(body)
    assert body["status"] == "ok"
    assert isinstance(body["activeMetrics"], list) and body["activeMetrics"]
    assert isinstance(body["clock"], int)


# ---------------------------------------------------------------------------
# GET /api/runs/latest/findings -- the frozen contract.
# ---------------------------------------------------------------------------

def test_latest_findings_has_more_than_zero_findings_after_startup(client):
    r = client.get("/api/runs/latest/findings")
    assert r.status_code == 200
    body = r.json()
    assert {"runId", "windowLabel", "findings"} <= set(body.keys())
    assert len(body["findings"]) > 0


def test_each_finding_matches_the_fixtures_key_set_and_shape(client):
    fixture_keys = set(FIXTURE["findings"][0].keys())
    r = client.get("/api/runs/latest/findings")
    body = r.json()

    for f in body["findings"]:
        assert set(f.keys()) == fixture_keys
        assert isinstance(f["id"], str)
        assert isinstance(f["metricId"], str)
        assert isinstance(f["metricLabel"], str)
        assert isinstance(f["unit"], str)
        assert isinstance(f["sliceLabel"], str)
        assert isinstance(f["tier"], str)
        assert isinstance(f["cause"], str)
        assert isinstance(f["action"], str)
        if f["tier"] == "PASS":
            assert f["action"] == "", "a PASS finding must carry no action"
        assert isinstance(f["owns"], list) and len(f["owns"]) <= 2
        if f["tier"] == "PASS":
            assert f["owns"] == [], "a PASS finding must carry no owns"
        for c in f["owns"]:
            assert set(c.keys()) == {"value", "pointsOfGap", "n"}
            assert isinstance(c["value"], str)
            assert isinstance(c["pointsOfGap"], (int, float))
            assert isinstance(c["n"], int)
        # Task 16: null when not computed, else {weeks, of} -- always present
        # as a key (checked above by the fixture key-set equality), never
        # omitted.
        if f["tier"] == "PASS":
            assert f["recurrence"] is None, "a PASS finding must never carry recurrence"
        if f["recurrence"] is not None:
            assert set(f["recurrence"].keys()) == {"weeks", "of"}
            assert isinstance(f["recurrence"]["weeks"], int)
            assert isinstance(f["recurrence"]["of"], int)
            assert 0 <= f["recurrence"]["weeks"] <= f["recurrence"]["of"]
        assert isinstance(f["observed"], (int, float))
        assert isinstance(f["gap"], (int, float))
        assert isinstance(f["confidence"], (int, float))
        assert isinstance(f["audiences"], list) and all(isinstance(a, str) for a in f["audiences"])
        assert isinstance(f["references"], list)
        for ref in f["references"]:
            assert set(ref.keys()) == {"kind", "value", "label"}
            assert isinstance(ref["value"], (int, float))
        assert isinstance(f["evidenceSql"], str)


def test_at_least_one_concern_or_worse_finding_carries_recurrence_on_the_sample(client):
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    concern_or_worse = [f for f in findings if f["tier"] in ("CONCERN", "BREACH")]
    assert concern_or_worse, "fixture assumption: at least one CONCERN+ finding exists"
    with_recurrence = [f for f in concern_or_worse if f["recurrence"] is not None]
    assert with_recurrence, "at least one CONCERN+ finding must carry recurrence on the sample"


def test_finding_to_json_matches_the_frozen_fixtures_key_set(client):
    # api.py's own serialiser (Controller ruling, task-5), exercised directly
    # against a real Finding rather than through the HTTP layer.
    run = STORE.get("latest")
    assert run is not None and run.findings
    produced = finding_to_json(run.findings[0])
    assert set(produced.keys()) == set(FIXTURE["findings"][0].keys())


def test_runs_latest_is_an_alias_for_the_most_recent_run(client):
    r = client.get("/api/runs/latest/findings")
    latest_body = r.json()
    r2 = client.get(f"/api/runs/{latest_body['runId']}/findings")
    assert r2.status_code == 200
    assert r2.json() == latest_body


# ---------------------------------------------------------------------------
# POST /api/sweep
# ---------------------------------------------------------------------------

def test_post_sweep_returns_a_run_id_that_the_findings_route_resolves(client):
    r = client.post("/api/sweep?wait=1")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "findingCount"}
    assert body["findingCount"] > 0

    r2 = client.get(f"/api/runs/{body['runId']}/findings")
    assert r2.status_code == 200
    assert r2.json()["runId"] == body["runId"]
    assert len(r2.json()["findings"]) == body["findingCount"]
    assert r2.json()["windowKind"] == "week"
    assert r2.json()["windowDays"] == 7


def test_post_sweep_defaults_to_a_week_window_when_no_param_is_given(client):
    # wait=1 is the synchronous path, kept exactly for callers like this
    # one that want the run rather than a job to poll.
    r = client.post("/api/sweep?wait=1")
    body = r.json()
    findings = client.get(f"/api/runs/{body['runId']}/findings").json()
    assert findings["windowKind"] == "week"
    assert findings["windowDays"] == 7


def test_post_sweep_with_a_month_window_returns_a_28_day_span(client):
    r = client.post("/api/sweep", params={"window": "month", "wait": 1})
    assert r.status_code == 200
    run_id = r.json()["runId"]

    findings = client.get(f"/api/runs/{run_id}/findings").json()
    assert findings["windowKind"] == "month"
    assert findings["windowDays"] == 28

    start_str, end_str = findings["windowLabel"].split("..")
    start = dt.date.fromisoformat(start_str)
    end = dt.date.fromisoformat(end_str)
    # windowLabel's end is the last INCLUDED day (end_ms - 1), so a 28-day
    # half-open window spans 27 days between its two printed dates.
    assert (end - start).days == 27

    # Restore "latest" to a normal week sweep so later tests in this
    # module-scoped client are not left depending on a month-length window.
    r2 = client.post("/api/sweep?wait=1")
    assert r2.json()["runId"] != run_id


def test_post_sweep_with_an_unknown_window_is_422(client):
    r = client.post("/api/sweep", params={"window": "fortnight"})
    assert r.status_code == 422
    error = r.json()["detail"]["error"]
    assert "week" in error and "month" in error


# ---------------------------------------------------------------------------
# GET /api/runs/{id}/safety
# ---------------------------------------------------------------------------

def test_run_safety_reports_the_woman_travelling_alone_summary(client):
    r = client.get("/api/runs/latest/safety")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "womanTravellingAloneAlerts", "escortPresentPct"}
    assert isinstance(body["womanTravellingAloneAlerts"], int)
    assert isinstance(body["escortPresentPct"], (int, float))
    assert body["womanTravellingAloneAlerts"] >= 0


def test_run_safety_for_an_unknown_run_is_404(client):
    r = client.get("/api/runs/no-such-run-ever/safety")
    assert r.status_code == 404
    assert r.json()


# ---------------------------------------------------------------------------
# GET /api/findings/{id}
# ---------------------------------------------------------------------------

def test_get_one_finding_by_id(client):
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    fid = findings[0]["id"]
    r = client.get(f"/api/findings/{fid}")
    assert r.status_code == 200
    assert r.json()["id"] == fid


# ---------------------------------------------------------------------------
# GET /api/findings/{id}/decompose
# ---------------------------------------------------------------------------

def test_decompose_defaults_to_vendor_and_the_rows_sum_to_the_gap(client):
    # The unsliced ota finding specifically, not just findings[0] -- a route
    # that always returns [] would pass a test that only checks rows
    # conditionally, which is exactly the gap this fix-wave closes.
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    ota = next(f for f in findings
              if f["metricId"] == "ota" and f["sliceLabel"] == "overall")
    r = client.get(f"/api/findings/{ota['id']}/decompose")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"findingId", "dim", "overallObserved", "gap", "rows"}
    assert body["findingId"] == ota["id"]
    assert body["dim"] == "VENDOR"
    assert body["rows"], "the unsliced ota finding must decompose into at least one row"
    assert set(body["rows"][0].keys()) == {
        "value", "label", "observed", "shareOfVolume", "pointsOfGap", "n"}
    assert sum(r["pointsOfGap"] for r in body["rows"]) == pytest.approx(body["gap"], abs=0.5)


def test_decompose_accepts_delay_reason(client):
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    ota = next(f for f in findings if f["metricId"] == "ota")
    r = client.get(f"/api/findings/{ota['id']}/decompose", params={"dim": "DELAY_REASON"})
    assert r.status_code == 200
    assert r.json()["dim"] == "DELAY_REASON"


def test_decompose_for_an_unknown_finding_is_404(client):
    r = client.get("/api/findings/no-such-finding-ever/decompose")
    assert r.status_code == 404
    assert r.json()


def test_decompose_for_an_unknown_dimension_is_422_naming_the_valid_values(client):
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    fid = findings[0]["id"]
    r = client.get(f"/api/findings/{fid}/decompose", params={"dim": "NOT_A_REAL_DIM"})
    assert r.status_code == 422
    error = r.json()["detail"]["error"]
    assert "DELAY_REASON" in error and "VENDOR" in error


# ---------------------------------------------------------------------------
# 404s -- unknown ids return a JSON body, not a bare error.
# ---------------------------------------------------------------------------

def test_unknown_run_id_is_404_with_a_json_body(client):
    r = client.get("/api/runs/no-such-run-ever/findings")
    assert r.status_code == 404
    assert r.json()


def test_unknown_finding_id_is_404_with_a_json_body(client):
    r = client.get("/api/findings/no-such-finding-ever")
    assert r.status_code == 404
    assert r.json()


# ---------------------------------------------------------------------------
# GET /api/outlook and /api/outlook/shifts -- Task 14's stated seasonal
# baseline. Never presented as prediction; every basis day is a real query.
# ---------------------------------------------------------------------------

def test_outlook_states_its_method_and_weights(client):
    r = client.get("/api/outlook")
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "seasonal-baseline-4w"
    assert body["basisWeeks"] == 4
    assert body["weights"] == [4, 3, 2, 1]
    assert len(body["projections"]) == len(set(registry.ACTIVE_METRICS))


def test_every_outlook_projection_carries_four_dated_runnable_basis_queries(client):
    body = client.get("/api/outlook?date=2026-07-29").json()
    assert body["targetDate"] == "2026-07-29"
    for p in body["projections"]:
        assert p["method"] == "seasonal-baseline-4w"
        assert len(p["basis"]) == 4
        assert [b["date"] for b in p["basis"]] == [
            "2026-07-22", "2026-07-15", "2026-07-08", "2026-07-01"]
        # A judge asking "where does that number come from" gets four queries.
        for b in p["basis"]:
            assert b["sql"] and "SELECT" in b["sql"].upper()
        assert {"projected", "intervalLow", "intervalHigh", "readiness",
                "action", "targetDate", "slice", "metric"} <= set(p)


def test_outlook_projection_is_the_weighted_mean_of_its_own_basis_values(client):
    """The response is self-checking: the projected value must be the 4/3/2/1
    weighted mean of the four basis values printed alongside it."""
    body = client.get("/api/outlook?date=2026-07-29&metric=ota").json()
    p = body["projections"][0]
    v = [b["value"] for b in p["basis"]]
    assert all(x is not None for x in v), "sample data should carry four Wednesdays"
    expected = (4 * v[0] + 3 * v[1] + 2 * v[2] + 1 * v[3]) / 10.0
    assert p["projected"] == pytest.approx(expected, abs=0.02)
    assert p["basisDaysUsed"] == 4


def test_outlook_rejects_an_unknown_metric(client):
    assert client.get("/api/outlook?metric=nope").status_code == 422
    assert client.get("/api/outlook/shifts?metric=nope").status_code == 422


def test_outlook_rejects_a_malformed_date(client):
    assert client.get("/api/outlook?date=29-07-2026").status_code == 422


def test_outlook_shifts_projects_one_row_per_shift_band(client):
    r = client.get("/api/outlook/shifts?date=2026-07-29")
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "no_show_rate"
    assert body["shifts"], "sample data carries shift bands"
    labels = [p["slice"] for p in body["shifts"]]
    assert len(labels) == len(set(labels))
    assert all(lab.startswith("shift ") for lab in labels)
    assert all(p["method"] == "seasonal-baseline-4w" for p in body["shifts"])


def test_outlook_shifts_action_names_a_seat_count_when_it_can(client):
    body = client.get("/api/outlook/shifts?date=2026-07-29").json()
    projected = [p for p in body["shifts"] if not p["withheld"]]
    if not projected:
        pytest.skip("no shift band in data/sample has four Wednesdays of history")
    assert any("planned seats" in p["action"] for p in projected)


def test_outlook_never_calls_itself_a_forecast_or_a_prediction(client):
    body = client.get("/api/outlook?date=2026-07-29").json()
    for p in body["projections"]:
        text = (p["action"] + " " + p["note"]).lower()
        assert "predict" not in text
        assert text.count("forecast") == text.count("not a forecast")


def test_brief_carries_the_outlook_line(client, monkeypatch):
    # Same convention as the brief tests below: no SARVAM_API_KEY in the test
    # env even if ../.env carries a real one, so this asserts the wiring and
    # never makes a live model call.
    monkeypatch.setenv("SARVAM_API_KEY", "")
    body = client.get("/api/runs/latest/brief?audience=TRANSPORT_MANAGER").json()
    assert body["source"] == "template"
    outlook_lines = [l for l in body["brief"].split("\n") if l.startswith("outlook:")]
    assert len(outlook_lines) == 1, body["brief"]
    assert "baseline" in outlook_lines[0]
    assert "predict" not in outlook_lines[0].lower()


# ---------------------------------------------------------------------------
# GET /api/health/feeds
# ---------------------------------------------------------------------------

def test_health_feeds_reports_one_row_per_feed(client):
    r = client.get("/api/health/feeds")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5
    expected_keys = {"feed", "rowsLoaded", "rowsRejected", "unmatchedKeys",
                     "nullCriticalFields", "confidence", "mustBeDisclosed", "quirks"}
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert isinstance(row["mustBeDisclosed"], bool)
        assert row["mustBeDisclosed"] is (row["confidence"] < 0.9)
        assert isinstance(row["quirks"], list)
        for q in row["quirks"]:
            assert set(q.keys()) == {"name", "rows", "detail"}

    # bill's slab-billing quirk is real on data/sample (this file's own fix
    # wave found it on data/real; data/sample is a real slice of the same
    # feed) and must NOT lower bill's confidence -- it is a billing mode.
    bill = next(row for row in rows if row["feed"] == "bill")
    assert any(q["name"] == "slab_billed_no_distance" for q in bill["quirks"])


# ---------------------------------------------------------------------------
# POST /api/replay/start|stop -- must not sleep for long.
# ---------------------------------------------------------------------------

def test_replay_start_advances_the_clock_and_stop_freezes_it(client):
    before = client.get("/api/health").json()["clock"]

    r = client.post("/api/replay/start", json={"speed": 1_000_000.0})
    assert r.status_code == 200
    assert r.json()["running"] is True

    time.sleep(0.02)
    during = client.get("/api/health").json()["clock"]
    assert during > before

    r2 = client.post("/api/replay/stop")
    assert r2.status_code == 200
    assert r2.json()["running"] is False

    stopped = client.get("/api/health").json()["clock"]
    time.sleep(0.01)
    assert client.get("/api/health").json()["clock"] == stopped


def test_replay_start_rejects_a_zero_or_negative_speed(client):
    for bad_speed in (0, -5.0):
        r = client.post("/api/replay/start", json={"speed": bad_speed})
        assert r.status_code == 422
        assert r.json()["detail"]["error"]
    client.post("/api/replay/stop")   # leave the clock stopped for later tests


def test_replay_start_rejects_a_speed_above_the_ceiling(client):
    r = client.post("/api/replay/start", json={"speed": 10_000_000.1})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]


def test_replay_start_accepts_the_speed_ceiling_itself(client):
    r = client.post("/api/replay/start", json={"speed": 10_000_000.0})
    assert r.status_code == 200
    client.post("/api/replay/stop")


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/brief
# ---------------------------------------------------------------------------

def test_brief_on_the_sample_run_is_non_empty_and_uses_the_template_without_a_key(
        client, monkeypatch):
    # No SARVAM_API_KEY in the test env (even if ../.env carries a real one for
    # the demo) -- the route must degrade to the template, and say so.
    monkeypatch.setenv("SARVAM_API_KEY", "")
    r = client.get("/api/runs/latest/brief", params={"audience": "TRANSPORT_MANAGER"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "audience", "brief", "source"}
    assert body["audience"] == "TRANSPORT_MANAGER"
    assert body["source"] == "template"
    assert len(body["brief"]) > 0


def test_brief_for_an_unknown_run_is_404(client):
    r = client.get("/api/runs/no-such-run-ever/brief")
    assert r.status_code == 404
    assert r.json()


def test_brief_for_an_unknown_audience_is_400(client):
    r = client.get("/api/runs/latest/brief", params={"audience": "NOT_A_REAL_AUDIENCE"})
    assert r.status_code == 400
    assert r.json()


# ---------------------------------------------------------------------------
# POST /api/dispatch/{run_id}
# ---------------------------------------------------------------------------

def test_dispatch_with_no_channels_configured_reports_not_configured_and_still_logs(
        client, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SES_FROM", raising=False)
    monkeypatch.delenv("SES_TO", raising=False)

    before = len(client.get("/api/dispatch/log").json())
    r = client.post("/api/dispatch/latest")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "dispatched"}
    assert len(body["dispatched"]) > 0

    all_channels = [ch for entry in body["dispatched"] for ch in entry["channels"]]
    assert len(all_channels) > 0
    for ch in all_channels:
        assert ch["delivered"] is False
        assert ch["detail"] == "not configured"
    for entry in body["dispatched"]:
        assert isinstance(entry["findingIds"], list)

    after = client.get("/api/dispatch/log").json()
    assert len(after) == before + len(body["dispatched"])


def test_dispatch_for_an_unknown_run_is_404(client):
    r = client.post("/api/dispatch/no-such-run-ever")
    assert r.status_code == 404
    assert r.json()


# ---------------------------------------------------------------------------
# GET /api/cost
# ---------------------------------------------------------------------------

def test_cost_snapshot_has_the_expected_shape(client):
    r = client.get("/api/cost")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "calls", "inputTokens", "outputTokens", "tokensPerCall", "inr",
        "inrPerOrgPerMonth", "employeesAtScale", "inrPerEmployeePerMonth",
        "byPurpose", "pricingConfigured", "rateIsApproximate", "latency",
    }


def test_cost_carries_measured_latency_for_the_startup_sweep(client):
    """Criterion 2 asks for latency by name. The app sweeps on startup,
    so by the time anything can call this the sweep and its metric
    queries have both been measured -- against the real registry, not a
    stub."""
    body = client.get("/api/cost").json()
    latency = body["latency"]
    assert latency["sweep"]["n"] >= 1
    assert latency["metric_query"]["n"] > 1
    assert latency["metric_query"]["p95Ms"] >= latency["metric_query"]["p50Ms"]
    # No model call is made in the test app, so the label is absent
    # rather than reported as a zero.
    assert "model_call" not in latency


# ---------------------------------------------------------------------------
# GET /api/dispatch/log
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET /api/employees/impact -- Task 15
# ---------------------------------------------------------------------------

def test_employees_impact_shape_and_totals_reconcile(client):
    r = client.get("/api/employees/impact", params={"runId": "latest"})
    assert r.status_code == 200
    body = r.json()
    expected_keys = {
        "runId", "window", "employeesImpacted", "ridersInWindow",
        "noShowLegs", "latePickupLegs", "avgPickupDelayMin", "medianPickupDelayMin",
        "employeeCausedDelayShare", "byShiftBand", "bySite", "byVendor",
        "costPerRider", "costPerRiderTrend"}
    assert set(body.keys()) == expected_keys
    assert set(body["window"].keys()) == {"start", "end", "label"}

    # The two properties that actually matter: employeesImpacted is a subset
    # of both "had any leg" and "had a no-show or late-pickup event".
    assert body["employeesImpacted"] <= body["ridersInWindow"]
    assert body["noShowLegs"] + body["latePickupLegs"] >= body["employeesImpacted"]

    if body["employeeCausedDelayShare"] is not None:
        assert 0.0 <= body["employeeCausedDelayShare"] <= 1.0

    for row in body["byShiftBand"]:
        assert set(row.keys()) == {"shiftBand", "legs", "noShows", "latePickups", "impacted"}
    bands = {row["shiftBand"] for row in body["byShiftBand"]}
    assert bands <= {"EARLY", "DAY", "EVENING", "NIGHT"}
    assert len(bands) >= 2, "fixture assumption: at least two shift bands appear in this window"

    for row in body["bySite"]:
        assert set(row.keys()) == {"site", "legs", "noShows", "latePickups", "impacted"}
    assert len(body["bySite"]) <= 10

    for row in body["byVendor"]:
        assert set(row.keys()) == {"vendor", "legs", "noShows", "latePickups", "impacted"}
    assert len(body["byVendor"]) <= 10


def test_employees_impact_default_run_id_is_latest(client):
    r = client.get("/api/employees/impact")
    assert r.status_code == 200
    latest = client.get("/api/runs/latest/findings").json()
    assert r.json()["runId"] == latest["runId"]


def test_employees_impact_for_an_unknown_run_is_404(client):
    r = client.get("/api/employees/impact", params={"runId": "no-such-run-ever"})
    assert r.status_code == 404
    assert r.json()


def test_dispatch_log_is_a_list_of_json_records(client):
    r = client.get("/api/dispatch/log")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        expected_keys = {"runId", "audience", "tier", "channels", "findingIds", "sentAtMs"}
        assert set(rows[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Provenance in the API -- UAT task 1. Whether the words on screen were
# written by Gen AI or by a deterministic path was previously readable only
# from the source. Both model-mediated responses now say so themselves, in
# the same vocabulary.
# ---------------------------------------------------------------------------

def test_the_brief_response_says_template_when_no_model_can_be_called(client, monkeypatch):
    # The honest half of the question: with no key there is no model call to
    # make, so the prose on screen is deterministic -- and the field SAYS so
    # rather than letting a reader assume Gen AI wrote it. Asserted with the
    # key removed so the test states a fact about the code, not about
    # whichever environment it happens to run in.
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    body = client.get("/api/runs/latest/brief").json()
    assert body["source"] == "template"


def test_the_ask_response_names_the_path_that_wrote_it(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    body = client.post("/api/ask", json={"question": "how is on-time?"}).json()
    assert body["withheld"] is True
    assert body["source"] == "withheld"
    assert body["answer"] is None


def test_every_ask_response_carries_a_source_field(client):
    # The console renders this; it must never be absent, on any path.
    body = client.post("/api/ask", json={"question": "how is on-time?"}).json()
    assert "source" in body
    assert body["source"] in {"sarvam", "withheld"}


# ---------------------------------------------------------------------------
# The user-facing refusal message on POST /api/ask. `reason` stays exactly
# as it was (the console shows it in the expandable trace); `message` is the
# sentence a person reads instead of "answer contained a figure no tool
# returned: 14.8".
# ---------------------------------------------------------------------------

def test_a_withheld_ask_response_carries_a_human_message_beside_the_reason(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    body = client.post("/api/ask", json={"question": "how is on-time?"}).json()
    assert body["withheld"] is True
    # Both fields, and they are not the same string.
    assert "SARVAM_API_KEY" in body["reason"]
    assert body["message"] and body["message"] != body["reason"]
    assert "SARVAM_API_KEY" not in body["message"]
    assert body["message"] == tools.MESSAGE_NOT_CONFIGURED


def test_every_ask_response_carries_a_message_field(client):
    # The console reads this unconditionally, so it must never be absent --
    # null on an answered response, a sentence on a withheld one.
    body = client.post("/api/ask", json={"question": "how is on-time?"}).json()
    assert "message" in body
    assert body["message"] is None or isinstance(body["message"], str)
    if body["withheld"]:
        assert body["message"]


# ---------------------------------------------------------------------------
# POST /api/ask `history` -- UAT task 3, the contract agreed with the console.
# Optional, chronological, excluding the current question; capped and
# truncated server-side, never a reason to refuse.
# ---------------------------------------------------------------------------

def test_ask_without_history_is_unchanged(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    r = client.post("/api/ask", json={"question": "how is on-time?"})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "how is on-time?"
    assert body["source"] == "withheld"


def test_ask_accepts_a_well_formed_history(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    r = client.post("/api/ask", json={
        "question": "and the night shift?",
        "history": [
            {"role": "user", "content": "which vendor is worst?"},
            {"role": "assistant", "content": "Aarav Petrov Travel."},
        ],
    })
    assert r.status_code == 200


def test_ask_ignores_malformed_history_rather_than_500ing(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    for junk in ("a string", 7, [None, "nope", {"role": "system", "content": "x"}],
                 [{"role": "user"}], [{"content": "no role"}], {"role": "user"}):
        r = client.post("/api/ask", json={"question": "still answerable?",
                                          "history": junk})
        assert r.status_code == 200, junk


def test_ask_truncates_an_oversized_history_rather_than_rejecting_it(client, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    huge = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 5_000}
            for i in range(50)]
    r = client.post("/api/ask", json={"question": "still answerable?", "history": huge})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# The outlook's DEFAULT day -- UAT task A. The default target was the day the
# window ends on, which on this dataset is a Saturday; the four preceding
# Saturdays carry no trips, so the card rendered four refusals and the
# feature looked broken while working perfectly one day later.
# ---------------------------------------------------------------------------

def test_the_default_outlook_day_is_one_that_actually_has_a_basis(client):
    body = client.get("/api/outlook/shifts").json()
    assert body["shifts"], "sample data carries shift bands"
    assert not all(p["withheld"] for p in body["shifts"]), (
        "the default day must not be one where every band is withheld")


def test_the_default_outlook_day_says_which_day_it_chose(client):
    body = client.get("/api/outlook/shifts").json()
    # The method line names the day it projected, so an auto-advanced target
    # is visible rather than silently substituted.
    assert body["targetDate"] == body["shifts"][0]["targetDate"]
    assert body["targetDateAutoSelected"] is True


def test_an_explicit_outlook_date_is_honoured_even_when_it_withholds(client):
    # The withheld path stays live and reachable: asking about a day with no
    # basis must still answer honestly about THAT day, not quietly move.
    body = client.get("/api/outlook/shifts?date=2026-08-01").json()
    assert body["targetDate"] == "2026-08-01"
    assert all(p["withheld"] for p in body["shifts"])
    assert body["targetDateAutoSelected"] is False


def test_the_plain_outlook_route_defaults_to_the_same_chosen_day(client):
    shifts = client.get("/api/outlook/shifts").json()
    plain = client.get("/api/outlook").json()
    assert plain["targetDate"] == shifts["targetDate"]
    assert plain["targetDateAutoSelected"] is True


# ---------------------------------------------------------------------------
# POST /api/sweep is asynchronous -- the deployed-instance bug. A full sweep
# over data/real is ~109 seconds; Render's proxy gives up long before that,
# so "Sweep now" either hung for a minute and a half or returned the
# platform's own 502 page. No retry fixes a synchronous call that outlives
# the proxy; the job has to stop being synchronous.
# ---------------------------------------------------------------------------

def _await_job(client, job_id, tries=600):
    for _ in range(tries):
        body = client.get(f"/api/sweep/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("sweep job never finished")


def test_sweep_accepts_immediately_with_a_pollable_job(client):
    r = client.post("/api/sweep?window=week")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "running"
    assert body["window"] == "week"
    assert body["jobId"]
    assert body["pollUrl"] == f"/api/sweep/{body['jobId']}"


def test_a_sweep_job_resolves_to_a_run_the_client_can_then_fetch(client):
    job_id = client.post("/api/sweep?window=week").json()["jobId"]
    done = _await_job(client, job_id)
    assert done["status"] == "done", done
    assert done["runId"]
    assert done["findingCount"] >= 0
    assert done["error"] is None
    findings = client.get(f"/api/runs/{done['runId']}/findings")
    assert findings.status_code == 200
    assert findings.json()["runId"] == done["runId"]


def test_an_unknown_sweep_job_is_a_404_not_a_hang(client):
    assert client.get("/api/sweep/nope").status_code == 404


def test_sweep_still_rejects_an_unknown_window_before_starting_any_work(client):
    r = client.post("/api/sweep?window=fortnight")
    assert r.status_code == 422
    assert "fortnight" in r.json()["detail"]["error"]


def test_the_synchronous_sweep_path_is_still_available_for_callers_that_want_it(client):
    r = client.post("/api/sweep?window=week&wait=1")
    assert r.status_code == 200
    body = r.json()
    assert body["runId"]
    assert isinstance(body["findingCount"], int)


def test_a_second_sweep_while_one_runs_joins_it_rather_than_starting_another(client):
    first = client.post("/api/sweep?window=week").json()
    second = client.post("/api/sweep?window=week").json()
    # Either the first finished between the two calls (a fresh job is then
    # correct), or it is still running and the second must have joined it
    # rather than queueing a second 109-second job.
    if client.get(f"/api/sweep/{first['jobId']}").json()["status"] == "running":
        assert second["jobId"] == first["jobId"]
    _await_job(client, second["jobId"])
