"""The HTTP surface the console, the delivery pipeline and the interrogator are
all written against. Task 6 adds /brief, /dispatch and /cost to this file;
a later task adds /ask -- that one does not exist here.

Bug F6: startup order is one explicit function, registered as the FastAPI
lifespan hook, and NOT an import side effect -- importing this module must
never open a DuckDB connection or touch the filesystem.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from contextlib import asynccontextmanager

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import forecast, ingest, registry
from .actions import action_for
from .compose import brief_with_source
from .decompose import decompose, valid_dims
from .delivery import DISPATCH_LOG, dispatch
from .model import COST
from .telemetry import LATENCY
from .schemas import Audience, Dimension, Finding, Slice
from .sweep import STORE, ReplayClock, sweep
from .tools import ask as ask_question

logger = logging.getLogger("signaldesk")

DAY_MS = 86_400_000

# Window parameter: month is 28 days, not calendar-month-variable, so a
# month's 4 trend-reference windows (references._trend shifts back by the
# window's OWN length -- Window.shifted_back) stay the same fixed length as
# the window itself rather than drifting across months of different sizes.
WINDOW_DAYS_BY_KIND = {"week": 7, "month": 28}

# Fix-wave minor: an unvalidated replay speed can freeze the console (0 or
# negative never advances the clock) or blow past anything a demo needs
# (a speed this high replays a 90-day dataset in under a second).
MAX_REPLAY_SPEED = 10_000_000.0


# Part A seam fix: the console must be able to feature-detect the optional
# endpoints of THIS build without probing them with a malformed request. It
# used to POST an empty question to /api/ask; the service correctly answers
# 422, the console read any non-2xx as "endpoint absent", and the floating
# assistant stayed permanently disabled against a working backend.
#
# The names are a fixed contract shared with the console. The list served is
# DERIVED from the routes create_app() actually registered, so deleting a
# route drops its capability with no second place to update.
OPTIONAL_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("ask", "POST", "/api/ask"),
    ("outlook", "GET", "/api/outlook"),
    ("decompose", "GET", "/api/findings/{finding_id}/decompose"),
    ("safety", "GET", "/api/runs/{run_id}/safety"),
    ("employees", "GET", "/api/employees/impact"),
    ("cost", "GET", "/api/cost"),
    ("dispatch-log", "GET", "/api/dispatch/log"),
)


def capabilities(app: FastAPI) -> list[str]:
    """Which of OPTIONAL_ENDPOINTS this app actually serves, in declared
    order. Read off app.routes rather than asserted, so the answer cannot
    drift from what is registered."""
    registered = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or ())
    }
    return [name for name, method, path in OPTIONAL_ENDPOINTS
            if (method, path) in registered]


class State:
    """Everything startup() constructs and every route reads. A plain object
    (not module globals) so create_app() can hand each TestClient its own
    fully-isolated instance rather than sharing one process-wide connection."""

    def __init__(self):
        self.con: duckdb.DuckDBPyConnection | None = None
        self.health: dict = {}
        self.clock: ReplayClock | None = None
        self.data_dir: str | None = None
        # Task 17: True only when SIGNALDESK_SYNTHETIC=1 AND data/synthetic/
        # actually loaded at least one feed -- /attribution's own feature-
        # detection gate reads this rather than re-checking the env var or
        # the filesystem itself.
        self.synthetic_loaded: bool = False


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

    # Task 17: additive and OFF by default -- a no-op unless SIGNALDESK_
    # SYNTHETIC=1 and data/synthetic/ (base's sibling) exists. Merged into
    # the same health dict sweep.py's metric-confidence lookup already reads
    # (extra keys it never looks up are harmless); state.synthetic_loaded is
    # the boolean /attribution's route gates on.
    synthetic_health = ingest.load_synthetic(con, base)
    health.update(synthetic_health)

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
    state.synthetic_loaded = bool(synthetic_health)

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
        # Fix wave 2: attached server-side by sweep.py for tier >= CONCERN
        # (capped at the top 25 by rank) -- the console reads this instead of
        # each Overview card fetching /decompose on mount. [] for a PASS/
        # WATCH finding, or one sweep.py did not attach owns to.
        "owns": [{"value": value, "pointsOfGap": round(points, 2), "n": n}
                 for value, points, n in f.owns],
        # Task 16: {weeks, of} -- how many of the last `of` (4) weeks this
        # same metric x slice was ALSO CONCERN-or-worse. null when not
        # computed (below the tier floor, past the top-25-by-rank cap, or a
        # PASS/WATCH finding) -- distinct from {weeks: 0, of: 4}, a genuine
        # one-off.
        "recurrence": ({"weeks": f.recurrence[0], "of": f.recurrence[1]}
                       if f.recurrence is not None else None),
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
        "windowDays": (run.window.end_ms - run.window.start_ms) // DAY_MS,
        "windowKind": run.window_kind,
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
    def post_sweep(window: str = "week"):
        kind = (window or "week").lower()
        if kind not in WINDOW_DAYS_BY_KIND:
            valid = ", ".join(WINDOW_DAYS_BY_KIND)
            raise HTTPException(status_code=422, detail={
                "error": f"unknown window {window!r}; valid values are {valid}"})
        run = sweep(state.con, state.clock, state.health,
                   window_days=WINDOW_DAYS_BY_KIND[kind], window_kind=kind)
        STORE.put(run)
        return {"runId": run.run_id, "findingCount": len(run.findings)}

    @app.get("/api/runs/{run_id}/findings")
    def get_run_findings(run_id: str):
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        return _run_to_json(run)

    @app.get("/api/runs/{run_id}/safety")
    def get_run_safety(run_id: str):
        # Controller ruling (marshal follow-up): the sharpest safety finding
        # in the dataset -- how many trips carried a WOMAN_TRAVELLING_ALONE
        # alert this window, and what fraction of those had an escort
        # present -- as its own small endpoint the console's Data health
        # page can show, rather than requiring a reader to find it inside
        # marshal_compliance's own decomposition.
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        return {
            "runId": run.run_id,
            "womanTravellingAloneAlerts": run.safety_alert_count,
            "escortPresentPct": round(run.safety_alert_escort_pct, 1),
        }

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
                "mustBeDisclosed": h.must_be_disclosed,
                "quirks": [{"name": name, "rows": rows, "detail": detail}
                          for name, rows, detail in h.quirks],
            }
            for h in state.health.values()
        ]

    @app.get("/api/health")
    def get_health():
        return {
            "status": "ok" if STORE.get("latest") is not None else "degraded",
            "activeMetrics": list(registry.ACTIVE_METRICS),
            "clock": state.clock.millis() if state.clock else None,
            # See OPTIONAL_ENDPOINTS: feature detection without a probe.
            "capabilities": capabilities(app),
        }

    @app.post("/api/replay/start")
    def post_replay_start(body: dict | None = None):
        if state.clock is None:
            raise HTTPException(status_code=503, detail={"error": "not started yet"})
        if body and "speed" in body:
            try:
                speed = float(body["speed"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail={
                    "error": f"speed must be a number, got {body['speed']!r}"})
            if not (0 < speed <= MAX_REPLAY_SPEED):
                raise HTTPException(status_code=422, detail={
                    "error": f"speed must be > 0 and <= {MAX_REPLAY_SPEED:g}, got {speed!r}"})
            state.clock.speed = speed
        state.clock.start()
        return {"running": True, "speed": state.clock.speed, "clockMs": state.clock.millis()}

    @app.post("/api/replay/stop")
    def post_replay_stop():
        if state.clock is None:
            raise HTTPException(status_code=503, detail={"error": "not started yet"})
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
        # Task 14: state.con so the brief can carry its deterministic outlook: line.
        text, source = brief_with_source(run, aud, con=state.con)
        return {"runId": run.run_id, "audience": aud.value, "brief": text, "source": source}

    @app.get("/api/findings/{finding_id}/decompose")
    def get_finding_decompose(finding_id: str, dim: str = "VENDOR"):
        f = STORE.finding(finding_id)
        if f is None:
            _not_found("finding", finding_id)
        try:
            rows = decompose(state.con, f, dim)
        except ValueError:
            raise HTTPException(status_code=422, detail={
                "error": f"unknown dimension {dim!r}; valid values are {valid_dims()}"})
        return {
            "findingId": f.id,
            "dim": dim.upper(),
            "overallObserved": round(f.observed, 2),
            "gap": round(f.gap, 2),
            "rows": [
                {
                    "value": r["value"],
                    "label": r["value"],
                    "observed": round(r["observed"], 2) if r["observed"] is not None else None,
                    "shareOfVolume": round(r["share_of_volume"], 4),
                    "pointsOfGap": round(r["points_of_gap"], 2),
                    "n": r["n"],
                }
                for r in rows
            ],
        }

    @app.get("/api/findings/{finding_id}/attribution")
    def get_finding_attribution(finding_id: str):
        """Task 17: an extra LENS on an existing finding, not a new finding
        source -- the flag-off path (state.synthetic_loaded False, the
        default) 404s naming SIGNALDESK_SYNTHETIC BEFORE the finding id is
        even looked up, so the console can feature-detect the capability
        with one call regardless of which finding it asks about."""
        if not state.synthetic_loaded:
            raise HTTPException(status_code=404, detail={
                "error": "synthetic delay-reasoning feeds are not loaded; "
                         "set SIGNALDESK_SYNTHETIC=1 and ensure data/synthetic/ exists"})
        f = STORE.finding(finding_id)
        if f is None:
            _not_found("finding", finding_id)
        rows = registry.delay_attribution(state.con, f.slice, f.window)
        return {
            "findingId": f.id,
            "synthetic": True,
            "rows": [
                {
                    "cause": r["cause"],
                    "share": round(r["share"], 4),
                    "n": r["n"],
                    "evidenceSql": r["evidence_sql"],
                }
                for r in rows
            ],
        }

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

    @app.get("/api/employees/impact")
    def get_employees_impact(runId: str = "latest"):
        """Task 15: employee-related delay and cost, previously invisible to
        the console entirely. Both delay readings appear, labelled apart:
        latePickupLegs/avgPickupDelayMin/medianPickupDelayMin are the delay
        an employee EXPERIENCES (their own pickup, late against their own
        planned time); employeeCausedDelayShare is the delay employees
        CAUSE (trips.delay_reason = 'EMPLOYEE'). All SQL lives in
        registry.py's own helpers -- this route only shapes the JSON."""
        run = STORE.get(runId)
        if run is None:
            _not_found("run", runId)
        window = run.window

        totals = registry.employee_impact_totals(state.con, window)
        by_shift = registry.employee_impact_by_dim(state.con, Dimension.SHIFT, window)
        by_site = registry.employee_impact_by_dim(state.con, Dimension.SITE, window, limit=10)
        by_vendor = registry.employee_impact_by_dim(state.con, Dimension.VENDOR, window, limit=10)

        cost_metric = registry.by_id("cost_per_rider")
        cost_per_rider = registry.evaluate(state.con, cost_metric, Slice.all(), window)
        cost_per_rider_trend = registry.trend_reference(state.con, cost_metric, Slice.all(), window)

        def _round(v, n=2):
            return round(v, n) if v is not None else None

        return {
            "runId": run.run_id,
            "window": {"start": window.start_ms, "end": window.end_ms, "label": window.label},
            "employeesImpacted": totals["employees_impacted"],
            "ridersInWindow": totals["riders_in_window"],
            "noShowLegs": totals["no_show_legs"],
            "latePickupLegs": totals["late_pickup_legs"],
            "avgPickupDelayMin": _round(totals["avg_pickup_delay_min"]),
            "medianPickupDelayMin": _round(totals["median_pickup_delay_min"]),
            "employeeCausedDelayShare": _round(totals["employee_caused_delay_share"], 4),
            "byShiftBand": [
                {"shiftBand": r["value"], "legs": r["legs"], "noShows": r["no_shows"],
                 "latePickups": r["late_pickups"], "impacted": r["impacted"]}
                for r in by_shift
            ],
            "bySite": [
                {"site": r["value"], "legs": r["legs"], "noShows": r["no_shows"],
                 "latePickups": r["late_pickups"], "impacted": r["impacted"]}
                for r in by_site
            ],
            "byVendor": [
                {"vendor": r["value"], "legs": r["legs"], "noShows": r["no_shows"],
                 "latePickups": r["late_pickups"], "impacted": r["impacted"]}
                for r in by_vendor
            ],
            "costPerRider": _round(cost_per_rider),
            "costPerRiderTrend": _round(cost_per_rider_trend),
        }

    @app.get("/api/cost")
    def get_cost():
        # Criterion 2 names cost AND latency; they answer the same
        # question and belong on the same panel. Labels a run never
        # exercised are absent, not zero.
        return {**COST.snapshot(), "latency": LATENCY.snapshot()}

    @app.post("/api/ask")
    def post_ask(body: dict):
        run_id = body.get("runId", "latest")
        question = (body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail={"error": "question must not be empty"})
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        # UAT task 3: `history` is optional and additive -- absent or empty
        # is exactly the pre-existing behaviour. It is never a reason to
        # refuse: tools.sanitize_history caps it, truncates it and drops
        # malformed entries rather than 4xx-ing a question that can still be
        # answered.
        result = ask_question(state.con, run, question, history=body.get("history"))
        return {
            "runId": run.run_id,
            "question": question,
            "answer": result["answer"],
            "withheld": result["withheld"],
            "reason": result["reason"],
            # UAT task 1: provenance, in the same vocabulary the brief uses.
            # "sarvam" means the model wrote these words and every figure in
            # them was checked against a tool result; "withheld" means
            # nothing the model wrote reached the screen.
            "source": result["source"],
            "trace": result["trace"],
        }

    # The default target used to be the day the run's window ENDS on, full
    # stop. On this dataset that is a Saturday, the four preceding Saturdays
    # carry no trips, and the outlook card therefore rendered four refusals
    # -- a working feature that looked broken, one day before a genuinely
    # useful line ("release about 1 of the ~13 planned seats for shift NIGHT
    # on Monday"). The default now ADVANCES, by at most a week, to the first
    # day the seasonal basis can actually speak for.
    #
    # Only the DEFAULT moves. An explicit ?date= is answered about that exact
    # day, withheld rows and all, because "no basis for the Saturday you
    # asked about" is the honest answer to that question and quietly
    # substituting a different day would be the dishonest one.
    OUTLOOK_DEFAULT_SEARCH_DAYS = 7
    _DAY_MS = 86_400_000

    def _first_day_with_a_basis(run) -> tuple[int, bool]:
        """(target_start_ms, auto_selected). Walks forward from the window's
        end, taking the first day whose shift outlook is not entirely
        withheld; falls back to the window end itself if a whole week of
        candidates has nothing, so the refusal is still shown rather than the
        route erroring."""
        start = run.window.end_ms
        for offset in range(OUTLOOK_DEFAULT_SEARCH_DAYS + 1):
            candidate = start + offset * _DAY_MS
            try:
                projections = forecast.shift_outlook(state.con, candidate)
            except Exception:
                logger.warning("api: shift outlook probe failed for %s",
                               candidate, exc_info=True)
                continue
            if projections and not all(p.withheld for p in projections):
                return candidate, offset > 0
        return start, False

    def _outlook_target(run_id: str, date: str | None = None):
        """The target date every outlook route projects onto.

        Defaults to the first day at or after the run window's end that the
        four-week same-weekday basis can actually speak for. `date`
        (YYYY-MM-DD, UTC) overrides it so a planner can ask about any shift
        day rather than only the next one. Returns (run, target_start_ms,
        auto_selected)."""
        run = STORE.get(run_id)
        if run is None:
            _not_found("run", run_id)
        if date is None:
            target, auto = _first_day_with_a_basis(run)
            return run, target, auto
        try:
            day = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.UTC)
        except ValueError:
            raise HTTPException(status_code=422, detail={
                "error": f"date must be YYYY-MM-DD, got {date!r}"})
        return run, int(day.timestamp() * 1000), False

    @app.get("/api/outlook")
    def get_outlook(runId: str = "latest", metric: str | None = None,
                    date: str | None = None):
        """Task 14: the shift readiness outlook as a STATED SEASONAL BASELINE.

        Not machine learning and never presented as prediction: each projection
        is the recency-weighted mean of the SAME WEEKDAY over the last four
        weeks, and carries the four basis observations with their dates, their
        values and the literal SQL that produced each one. All arithmetic lives
        in forecast.py over registry.evaluate(); this route only shapes JSON.
        """
        run, target, auto_selected = _outlook_target(runId, date)
        if metric is not None:
            try:
                registry.by_id(metric)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"error": str(exc)})
            ids = (metric,)
        else:
            ids = None
        projections = forecast.outlook(state.con, target, ids)
        return {
            "runId": run.run_id,
            "method": forecast.METHOD,
            "basisWeeks": forecast.BASIS_WEEKS,
            "weights": list(forecast.WEIGHTS),
            "targetDate": projections[0].target_date if projections else None,
            "targetStartMs": target,
            # True when no ?date= was given and the default ADVANCED past a
            # day with no basis -- so the card can say which day it is really
            # talking about rather than implying it was asked for.
            "targetDateAutoSelected": auto_selected,
            "projections": [p.to_json() for p in projections],
        }

    @app.get("/api/outlook/shifts")
    def get_outlook_shifts(runId: str = "latest", metric: str = "no_show_rate",
                           date: str | None = None):
        """One projection per shift band, worst readiness first. no_show_rate by
        default because its action names how many SEATS to release -- planned
        headcount is the number a facilities head can actually act on."""
        run, target, auto_selected = _outlook_target(runId, date)
        try:
            registry.by_id(metric)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)})
        projections = forecast.shift_outlook(state.con, target, metric)
        return {
            "runId": run.run_id,
            "metric": metric,
            "method": forecast.METHOD,
            "basisWeeks": forecast.BASIS_WEEKS,
            "weights": list(forecast.WEIGHTS),
            "targetDate": projections[0].target_date if projections else None,
            "targetStartMs": target,
            "targetDateAutoSelected": auto_selected,
            "shifts": [p.to_json() for p in projections],
        }

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
