"""api.py: the HTTP contract the console, delivery and the interrogator are
written against. GET /api/runs/{id}/findings is a FROZEN contract (Controller
ruling, task-5) -- checked here against handoff/fake-findings.json's key set,
not just "some JSON came back".

One module-scoped app/TestClient (startup pointed at data/sample) so the whole
file stays well under the ~20s budget: a fresh DuckDB load per test would blow
that on its own.
"""
from __future__ import annotations

import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

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
    assert set(body["activeMetrics"]) == {"ota", "otd", "vendor_ota", "no_show_rate"}
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
        assert isinstance(f["observed"], (int, float))
        assert isinstance(f["gap"], (int, float))
        assert isinstance(f["confidence"], (int, float))
        assert isinstance(f["audiences"], list) and all(isinstance(a, str) for a in f["audiences"])
        assert isinstance(f["references"], list)
        for ref in f["references"]:
            assert set(ref.keys()) == {"kind", "value", "label"}
            assert isinstance(ref["value"], (int, float))
        assert isinstance(f["evidenceSql"], str)


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
    r = client.post("/api/sweep")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "findingCount"}
    assert body["findingCount"] > 0

    r2 = client.get(f"/api/runs/{body['runId']}/findings")
    assert r2.status_code == 200
    assert r2.json()["runId"] == body["runId"]
    assert len(r2.json()["findings"]) == body["findingCount"]


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
    findings = client.get("/api/runs/latest/findings").json()["findings"]
    fid = findings[0]["id"]
    r = client.get(f"/api/findings/{fid}/decompose")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"findingId", "dim", "overallObserved", "gap", "rows"}
    assert body["findingId"] == fid
    assert body["dim"] == "VENDOR"
    if body["rows"]:
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
# GET /api/health/feeds
# ---------------------------------------------------------------------------

def test_health_feeds_reports_one_row_per_feed(client):
    r = client.get("/api/health/feeds")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5
    expected_keys = {"feed", "rowsLoaded", "rowsRejected", "unmatchedKeys",
                     "nullCriticalFields", "confidence"}
    for row in rows:
        assert set(row.keys()) == expected_keys


# ---------------------------------------------------------------------------
# POST /api/replay/start|stop -- must not sleep for long.
# ---------------------------------------------------------------------------

def test_replay_start_advances_the_clock_and_stop_freezes_it(client):
    before = client.get("/api/health").json()["clock"]

    r = client.post("/api/replay/start", json={"speed": 1_000_000_000.0})
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
        "byPurpose", "pricingConfigured", "rateIsApproximate",
    }


# ---------------------------------------------------------------------------
# GET /api/dispatch/log
# ---------------------------------------------------------------------------

def test_dispatch_log_is_a_list_of_json_records(client):
    r = client.get("/api/dispatch/log")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        expected_keys = {"runId", "audience", "tier", "channels", "findingIds", "sentAtMs"}
        assert set(rows[0].keys()) == expected_keys
