# Signal Desk

An agent that watches enterprise commute operations, works out what a transport
manager needs to know **before they ask**, and sends it — with the reasoning and
the originating SQL attached.

Built for the MoveInSync hackathon, *Agentic Intelligence & Reporting Layer for
Enterprise Mobility*, 5 September 2026.

> **The one rule everything rests on: the model never computes a number and never
> writes SQL.** Rules decide what is wrong and who cares; a metric registry answers
> what the figures are; the model only turns settled findings into language. That is
> why nothing on screen can be a hallucinated figure.

---

## What it does

```
SENSE ──▶ REASON ──▶ COMPOSE ──▶ ACT
```

1. **Sense.** On a clock tick — no prompt — the service loads the provided dataset
   (615k trips, 1.6M rider legs, 621k bill lines, 513k ratings, 52k alerts) into an
   embedded DuckDB, quarantining malformed rows and *counting* them rather than
   dropping them silently.
2. **Reason.** Pure rules compare every metric — overall and sliced by tenant, site,
   vendor, mode, direction and shift band — against its own 4-week trend and its
   peers, and emit ranked findings: tier (PASS / WATCH / CONCERN / BREACH), cause,
   audience, confidence, and the exact SQL that produced the number.
3. **Compose.** Sarvam (`sarvam-105b`) writes a short brief for a named audience
   from the findings — prose only. Every figure in the narrative is validated
   against the findings; if the model invents one, the brief ships from a
   deterministic template instead.
4. **Act.** The brief is routed by severity to Slack (and SES email), and the
   dispatch is logged with the finding ids it was built from.

A replay clock advances simulated time at 60×, so the 90 days of data play out on
stage and findings appear live — the same loop, with the clock set to *now*, is
the production version.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Service | **Python 3.12 · FastAPI · uvicorn** | One stateless process, no queue, no backing database |
| Data | **DuckDB 1.5** (embedded, in-process) | Reads 570 MB of CSV directly, aggregates 615k rows in milliseconds; the source path is one argument (`local dir` today, `s3://` via `httpfs` tomorrow) |
| Model | **Sarvam `sarvam-105b`** via the OpenAI-compatible SDK | Language only — one call per brief, so cost is flat in data volume (≈₹0.10 per brief) |
| Delivery | Slack incoming webhook · AWS SES (boto3) | Routed by tier: BREACH/CONCERN → both, WATCH → Slack, PASS → nothing |
| Console | **React 19 · Vite 8 · TypeScript** | Thin client over a documented HTTP contract |
| Tests | pytest · Vitest + Testing Library | Every guard is "break-it-to-prove-it" tested; a grep test enforces that SQL lives in exactly two modules |

Architecture, seams and the data flow: **[`docs/architecture.md`](docs/architecture.md)**.

## Prerequisites

- **Python 3.12** and **Node 22** (`nvm use` reads `.nvmrc`; Node 18 fails on Vite 8)
- The provided dataset unpacked into `data/real/` (not committed — ~570 MB). A
  3.5 MB stratified sample is committed at `data/sample/` and is what the tests use.
- Optional, for real delivery and the model brief: a Slack incoming webhook, a
  Sarvam API key, SES sandbox credentials. **Without them nothing breaks** — the
  brief ships from the template and the dispatch log says `not configured`.

## Run it

```sh
# 1. secrets — .env is git-ignored; never commit a webhook URL, it is a credential
cp .env.example .env            # fill SLACK_WEBHOOK_URL, SARVAM_API_KEY; SES vars optional

# 2. the service (sweeps once on startup, unprompted — watch for the log line)
cd service
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
SIGNALDESK_DATA=../data/real .venv/bin/uvicorn signaldesk.api:app --port 8080
#   -> INFO sweep run_id=run-... findings=... (unprompted, on startup)

# 3. the console, in a second terminal (proxies /api to :8080)
cd console
nvm use && npm install && npm run dev        # http://localhost:5173
```

Point `SIGNALDESK_DATA` at `../data/sample` for a 5-second start while developing.

### Drive it by hand

```sh
curl -s localhost:8080/api/health                          # {"status":"ok","activeMetrics":[...],"clock":...}
curl -s localhost:8080/api/runs/latest/findings | head -c 600   # ranked findings, evidenceSql on each
curl -s -X POST localhost:8080/api/sweep                   # {"runId":"run-...","findingCount":N}
curl -s "localhost:8080/api/runs/latest/brief?audience=TRANSPORT_MANAGER"
curl -s -X POST localhost:8080/api/dispatch/latest         # sends to Slack/SES if configured; logs either way
curl -s localhost:8080/api/health/feeds                    # rows loaded / quarantined / confidence per feed
curl -s localhost:8080/api/cost                            # tokens, rupees, per-organisation extrapolation
curl -s -X POST localhost:8080/api/replay/start            # 60x replay; /api/replay/stop freezes it
```

Every finding carries `evidenceSql`. Paste it into the DuckDB CLI against the same
data and you get the same number — that is the answer to "where did this come from".

## Test it

```sh
cd service && .venv/bin/pytest -q        # ~90 tests on data/sample; pytest.ini sets the path
cd console && npm test
```

Add `SIGNALDESK_DATA=../data/real` to run the data tests against the full dataset.

## Data

`docs/real-dataset-mapping.md` documents what the five feeds actually contain and
their deliberate quirks — `trip_id` in three formats, epochs as comma-strings,
dtype drift across months, negative distances, a stray `"False"` in `severity`.
The ingest normalises all of them at one boundary and reports what it could not
read as a per-feed confidence that the brief discloses when it drops below 0.9.

## Repository layout

```
service/signaldesk/   the agent — ingest → registry → references → verdict → sweep → compose → delivery → api
service/tests/        pytest suite (runs on data/sample)
console/              the React console
docs/                 architecture, design spec, build plan, dataset mapping, judge review
handoff/              per-lane build briefs and the frozen API fixture (fake-findings.json)
data/sample/          committed 3.5 MB stratified sample; data/real/ is the full dataset (git-ignored)
scripts/              environment and setup helpers
```

## What we deliberately did not build

Forecasting or predictive risk scoring (cannot be done credibly in six hours and
invites a question we cannot answer); vernacular feedback translation (the dataset
has no free text); authentication, a historical pipeline, vendor-system
integration, write-back. `OBJECTIVES.md` records each decision.

## Status

Build day 5 Sep 2026. Committed and reviewed: contracts, ingest, metric registry,
references and verdict engine, sweep + replay clock + API. Landing this morning:
the Sarvam brief, validator and Slack/SES delivery; then the console. The build
plan with the running order is `docs/superpowers/plans/2026-09-05-signal-desk-python-build.md`.
