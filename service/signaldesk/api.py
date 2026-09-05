"""The HTTP surface the console, the delivery pipeline and the interrogator are
all written against. Task 6 adds /brief, /dispatch and /cost to this file;
a later task adds /ask -- that one does not exist here.

Bug F6: startup order is one explicit function, registered as the FastAPI
lifespan hook, and NOT an import side effect -- importing this module must
never open a DuckDB connection or touch the filesystem.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import ingest, registry
from .actions import action_for
from .compose import brief_with_source
from .delivery import DISPATCH_LOG, dispatch
from .model import COST
from .schemas import Audience, Finding
from .sweep import STORE, ReplayClock, sweep

logger = logging.getLogger("signaldesk")

DAY_MS = 86_400_000


class State:
    """Everything startup() constructs and every route reads. A plain object
    (not module globals) so create_app() can hand each TestClient its own
    fully-isolated instance rather than sharing one process-wide connection."""

    def __init__(self):
        self.con: duckdb.DuckDBPyConnection | None = None
        self.health: dict = {}
        self.clock: ReplayClock | None = None
        self.data_dir: str | None = None


def _midnight_utc_plus_one_day(ms: int) -> int:
    """The demo's initial simulated "now": midnight UTC of the day AFTER the
    last trip in the loaded data, so a rerun of the same dataset always opens
    on the same window (Controller ruling, task-5). Verified against the
    frozen fixture: data/sample's last trip is 2026-07-31, and this yields
    2026-08-01T00:00:00Z = 1785542400000, the fixture's run id and window
    label exactly."""
    midnight = (ms // DAY_MS) * DAY_MS
    return midnight + DAY_MS


def startup(state: State, data_dir: str | None = None):
    """bug F6, in one function: load the feeds, compute health, construct the
    clock, sweep once, store the run -- so the console opens on a completed
    sweep rather than an empty shell. Never run on import."""
    # Root logger defaults to WARNING with no handler -- plain uvicorn
    # startup would otherwise silently swallow the one INFO line the demo
    # points at. basicConfig is a no-op if something else already configured
    # logging, so this is safe to call every startup.
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    base = data_dir or os.environ.get("SIGNALDESK_DATA", "../data/sample")

    con = duckdb.connect()
    health = ingest.load_all(con, ingest.source_for(base))

    override = os.environ.get("SIGNALDESK_CLOCK_MS")
    now_ms = int(override) if override else _midnight_utc_plus_one_day(
        ingest.latest_scheduled_ms(con))
    clock = ReplayClock(now_ms=now_ms)

    run = sweep(con, clock, health)
    STORE.put(run)

    state.con = con
    state.health = health
    state.clock = clock
    state.data_dir = base

    # The demo points at this exact line: the sweep that ran unprompted, on
    # startup, before any console loaded or any question was asked.
    logger.info("sweep run_id=%s findings=%d (unprompted, on startup)",
                run.run_id, len(run.findings))


def finding_to_json(f: Finding) -> dict:
    """The frozen contract (Controller ruling, task-5): EXACTLY the shape of
    handoff/fake-findings.json's `findings[]` entries. Three teams build
    against this file; changing a key name here breaks all three."""
    metric = registry.by_id(f.metric_id)
    return {
        "id": f.id,
        "metricId": f.metric_id,
        "metricLabel": metric.label,
        "unit": metric.unit,
        "sliceLabel": f.slice.label,
        "tier": f.tier.name,
        "cause": f.cause.value,
        "action": action_for(f),
        "observed": round(f.observed, 2),
        "gap": round(f.gap, 2),
        "confidence": round(f.confidence, 2),
        # Filtered through the Audience enum's own declaration order rather
        # than iterating the frozenset directly: str hashing is randomised
        # per-process, so frozenset iteration order is not stable across runs.
        "audiences": [a.value for a in Audience if a in f.audiences],
        "references": [
            {"kind": r.kind.value, "value": round(r.value, 2), "label": r.label}
            for r in f.refs
        ],
        "evidenceSql": f.evidence_sql,
    }


def _run_to_json(run) -> dict:
    return {
        "runId": run.run_id,
        "windowLabel": run.window.label,
        "findings": [finding_to_json(f) for f in run.findings],
    }


def _not_found(kind: str, ident: str):
    raise HTTPException(status_code=404, detail={"error": f"no {kind} {ident!r}"})


def create_app(data_dir: str | None = None) -> FastAPI:
    """`data_dir` lets a test point startup at data/sample without mutating
    SIGNALDESK_DATA for the whole process (Controller ruling, task-5)."""
    state = State()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        startup(state, data_dir)
        yield

    app = FastAPI(lifespan=lifespan)

    origins = [o.strip() for o in
              os.environ.get("SIGNALDESK_CORS_ORIGINS", "http://localhost:5173").split(",")
              if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.post("/api/sweep")
    def post_sweep():
        run = sweep(state.con, state.clock, state.health)
        STORE.put(run)
        return {"runId": run.run_id, "findingCount": len(run.findings)}

    @app.get("/api/runs/{run_id}/findings")
    def get_run_findings(run_id: str):
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        return _run_to_json(run)

    @app.get("/api/findings/{finding_id}")
    def get_finding(finding_id: str):
        f = STORE.finding(finding_id)
        if f is None:
            _not_found("finding", finding_id)
        return finding_to_json(f)

    @app.get("/api/health/feeds")
    def get_health_feeds():
        return [
            {
                "feed": h.feed,
                "rowsLoaded": h.rows_loaded,
                "rowsRejected": h.rows_rejected,
                "unmatchedKeys": h.unmatched_keys,
                "nullCriticalFields": h.null_critical_fields,
                "confidence": round(h.confidence, 2),
            }
            for h in state.health.values()
        ]

    @app.get("/api/health")
    def get_health():
        return {
            "status": "ok" if STORE.get("latest") is not None else "degraded",
            "activeMetrics": list(registry.TIER_1_METRICS),
            "clock": state.clock.millis() if state.clock else None,
        }

    @app.post("/api/replay/start")
    def post_replay_start(body: dict | None = None):
        if body and "speed" in body:
            state.clock.speed = float(body["speed"])
        state.clock.start()
        return {"running": True, "speed": state.clock.speed, "clockMs": state.clock.millis()}

    @app.post("/api/replay/stop")
    def post_replay_stop():
        state.clock.stop()
        return {"running": False, "clockMs": state.clock.millis()}

    @app.get("/api/runs/{run_id}/brief")
    def get_run_brief(run_id: str, audience: str = "TRANSPORT_MANAGER"):
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        try:
            aud = Audience(audience)
        except ValueError:
            valid = ", ".join(a.value for a in Audience)
            raise HTTPException(status_code=400,
                                detail={"error": f"unknown audience {audience!r}; "
                                                 f"valid values are {valid}"})
        text, source = brief_with_source(run, aud)
        return {"runId": run.run_id, "audience": aud.value, "brief": text, "source": source}

    @app.post("/api/dispatch/{run_id}")
    def post_dispatch(run_id: str, body: dict | None = None):
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        audiences = None
        if body and body.get("audiences"):
            try:
                audiences = [Audience(a) for a in body["audiences"]]
            except ValueError as e:
                raise HTTPException(status_code=400, detail={"error": str(e)})
        records = dispatch(run, audiences)
        return {
            "runId": run.run_id,
            "dispatched": [
                {
                    "audience": r.audience,
                    "tier": r.tier,
                    "channels": [
                        {"channel": c.channel, "delivered": c.delivered, "detail": c.detail}
                        for c in r.channels
                    ],
                    "findingIds": r.finding_ids,
                }
                for r in records
            ],
        }

    @app.get("/api/cost")
    def get_cost():
        return COST.snapshot()

    @app.get("/api/dispatch/log")
    def get_dispatch_log():
        return [
            {
                "runId": r.run_id,
                "audience": r.audience,
                "tier": r.tier,
                "channels": [
                    {"channel": c.channel, "delivered": c.delivered, "detail": c.detail}
                    for c in r.channels
                ],
                "findingIds": r.finding_ids,
                "sentAtMs": r.sent_at_ms,
            }
            for r in DISPATCH_LOG
        ]

    return app


# The process-wide app: `uvicorn signaldesk.api:app`. Constructing it does
# NOT run startup() -- that only fires on the lifespan event when a server
# (or a TestClient used as a context manager) actually starts serving.
app = create_app()
