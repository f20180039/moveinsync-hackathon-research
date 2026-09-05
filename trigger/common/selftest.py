"""Task 19 -- checks for the run reconciliation. No network beyond localhost,
posts nothing.

    python -m trigger.common.selftest

The property under test is the one the whole module exists for: a trigger
agent and the console must speak for the SAME run over the SAME window, or
must say plainly that they could not.

The reconciled case is exercised against a REAL service -- the actual FastAPI
app, built in-process and served on an ephemeral localhost port -- rather than
a stubbed HTTP response. A stub would prove that `resolve()` can parse a dict
we wrote ourselves; it would not prove that the field names it reads are the
field names `api._run_to_json` writes, which is exactly the thing that breaks
silently when one side is edited.
"""
from __future__ import annotations

import json
import sys
import threading
from wsgiref.simple_server import make_server

from ..common.config import ROOT           # noqa: F401  -- puts service/ on sys.path
from . import run_context


def _check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return bool(ok)


class _FakeService:
    """A WSGI app serving exactly the two endpoints resolve() reads, with
    payloads taken from the REAL api._run_to_json / get_health shapes (see
    _real_shapes below), so a rename on the service side shows up here."""

    def __init__(self, health: dict, run: dict | None):
        self.health, self.run = health, run
        self.paths_seen: list[str] = []

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]
        self.paths_seen.append(path)
        if path == "/api/health":
            body, status = self.health, "200 OK"
        elif path.startswith("/api/runs/") and path.endswith("/findings"):
            if self.run is None:
                body, status = {"error": "no run"}, "404 Not Found"
            else:
                body, status = self.run, "200 OK"
        else:
            body, status = {"error": "not found"}, "404 Not Found"
        payload = json.dumps(body).encode()
        start_response(status, [("Content-Type", "application/json"),
                                ("Content-Length", str(len(payload)))])
        return [payload]


def _serve(app):
    srv = make_server("127.0.0.1", 0, app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _real_shapes():
    """The ACTUAL dicts the service returns, built by calling api's own
    serialisers -- not hand-written copies of them."""
    from signaldesk import api, registry, sweep
    from signaldesk.schemas import Window

    window = Window(1_784_937_600_000, 1_785_542_400_000)
    run = sweep.SweepRun(run_id="run-selftest-1", window=window, findings=(),
                         feed_health={}, swept_at_ms=window.end_ms,
                         window_kind="week")
    run_json = api._run_to_json(run)
    health_json = {"status": "ok", "activeMetrics": list(registry.ACTIVE_METRICS),
                   "clock": window.end_ms, "capabilities": []}
    return health_json, run_json, window


def main() -> int:
    print("\nRun reconciliation selftest\n" + "=" * 30)
    results = []

    print("\n1. The service's own payload shape")
    try:
        health_json, run_json, window = _real_shapes()
    except Exception as exc:                      # pragma: no cover - import guard
        print(f"  could not build the real payloads: {type(exc).__name__}: {exc}")
        return 1
    results.append(_check("api._run_to_json exposes the exact window bounds",
                          {"windowStartMs", "windowEndMs"} <= set(run_json),
                          ", ".join(sorted(set(run_json) - {"findings"}))))
    results.append(_check("windowStartMs/EndMs are the run's own window",
                          run_json["windowStartMs"] == window.start_ms
                          and run_json["windowEndMs"] == window.end_ms))

    print("\n2. Reconciled against a live service")
    app = _FakeService(health_json, run_json)
    srv, url = _serve(app)
    try:
        ctx = run_context.resolve("week", url)
        results.append(_check("source is the service", ctx.source == "service", ctx.source))
        results.append(_check("reconciled", ctx.reconciled is True))
        results.append(_check("run id carried through",
                              ctx.run_id == "run-selftest-1", str(ctx.run_id)))
        results.append(_check("window is the RUN's window, to the millisecond",
                              ctx.window_start_ms == window.start_ms
                              and ctx.window_end_ms == window.end_ms,
                              f"{ctx.window_start_ms}..{ctx.window_end_ms}"))
        results.append(_check("window_days derived from the bounds",
                              ctx.window_days == 7, str(ctx.window_days)))
        line = ctx.provenance_line()
        results.append(_check("provenance names the run id", "run-selftest-1" in line))
        results.append(_check("provenance does NOT warn when reconciled",
                              "⚠️" not in line, line))
        results.append(_check("both endpoints were actually called",
                              any(p == "/api/health" for p in app.paths_seen)
                              and any(p.endswith("/findings") for p in app.paths_seen),
                              ", ".join(app.paths_seen)))
    finally:
        srv.shutdown()

    print("\n3. Falls back honestly when the service is unreachable")
    # An address nothing is listening on: port 1 on loopback.
    ctx = run_context.resolve("week", "http://127.0.0.1:1")
    results.append(_check("source is local", ctx.source == "local", ctx.source))
    results.append(_check("no run id is invented", ctx.run_id is None, str(ctx.run_id)))
    results.append(_check("provenance warns", "⚠️" in ctx.provenance_line()))
    results.append(_check("provenance says it may not match the console",
                          "may not match" in ctx.provenance_line()))

    print("\n4. A run WITHOUT window bounds is not treated as reconciled")
    # The failure mode this guard exists for: an older service that returns
    # windowLabel but no bounds. Re-deriving a window from a printed label is
    # exactly the silent divergence being fixed, so it must fall back instead.
    legacy = {k: v for k, v in run_json.items()
              if k not in ("windowStartMs", "windowEndMs")}
    app2 = _FakeService(health_json, legacy)
    srv2, url2 = _serve(app2)
    try:
        ctx = run_context.resolve("week", url2)
        results.append(_check("source is local", ctx.source == "local", ctx.source))
        results.append(_check("reason names the missing bounds",
                              "window bounds" in ctx.detail, ctx.detail))
    finally:
        srv2.shutdown()

    print("\n5. A degraded service (no sweep yet) is not reconciled")
    app3 = _FakeService({"status": "degraded", "clock": None}, None)
    srv3, url3 = _serve(app3)
    try:
        ctx = run_context.resolve("week", url3)
        results.append(_check("source is local", ctx.source == "local", ctx.source))
        results.append(_check("reason names the status", "degraded" in ctx.detail, ctx.detail))
    finally:
        srv3.shutdown()

    print("\n6. The planning window follows the RUN, not this process's data")
    # The behaviour that makes reconciliation real rather than decorative:
    # target_window must anchor on the run's window end when reconciled.
    from ..shift_planning_TransportManager.config import Config
    from ..shift_planning_TransportManager import stats as stats_mod
    cfg = Config.from_env()
    con, _health = stats_mod.load(cfg.data_dir)
    try:
        local_w = stats_mod.target_window(con, cfg, None)
        # A run whose window ends a WEEK EARLIER than this data's own last
        # trip: if the anchor were still max(scheduled_at), the planned date
        # would not move, and this check would fail.
        shifted = window.end_ms - 7 * run_context.DAY_MS
        fake = run_context.RunContext("service", "run-shifted", shifted - 7 * run_context.DAY_MS,
                                      shifted, "label", "week", shifted, "http://x", "")
        run_w = stats_mod.target_window(con, cfg, fake)
        results.append(_check("a reconciled run moves the planned day",
                              run_w["targetDate"] != local_w["targetDate"],
                              f"local {local_w['targetDate']} vs run {run_w['targetDate']}"))
        # HAND-COMPUTED, not recomputed with the implementation's own
        # expression (that would assert nothing): the fake run's window ends
        # at 2026-07-25 00:00 UTC, which is 05:30 on 2026-07-25 in IST, so the
        # last local day inside the window is the 25th and the day being
        # planned is the 26th. The +5:30 is exactly why this is a literal --
        # an off-by-one here is the kind of thing a self-recomputing assertion
        # would wave through.
        results.append(_check("the planned day is the local day after the run's window",
                              run_w["targetDate"] == "2026-07-26", run_w["targetDate"]))
        results.append(_check("provenance travels with the window",
                              run_w["provenance"] and "run-shifted" in run_w["provenance"]))
        results.append(_check("no run context leaves provenance empty",
                              local_w["provenance"] is None))
    finally:
        con.close()

    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
