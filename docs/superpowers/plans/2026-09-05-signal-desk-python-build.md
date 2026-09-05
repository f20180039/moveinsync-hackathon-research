# Signal Desk — build-day plan (Python)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent that sweeps enterprise commute data unprompted, ranks what a transport manager needs to know against a reference point, explains *why*, and delivers it to Slack and email with the reasoning and the originating SQL attached.

**Architecture:** Four layers, one hard seam. Tolerant CSV ingest into embedded DuckDB with a rejects quarantine; a metric registry that is the only thing holding SQL; pure functions comparing each metric to its reference points and emitting ranked findings; the model turning settled findings into language and answering questions through four validated tools. **No arithmetic passes through the model.**

**Tech Stack:** Python 3.12 · FastAPI · uvicorn · DuckDB 1.5.5 (`duckdb` package) · OpenAI Python SDK against Sarvam · boto3 (SES, S3) · React 19.2 · **Vite 8** · TypeScript 6 · pytest · Vitest 5 + Testing Library

**Spec:** [`docs/superpowers/specs/2026-09-04-signal-desk-design.md`](../specs/2026-09-04-signal-desk-design.md) — **read §15 (Amendment 1.1) first**; it supersedes the body's Java signatures and Render/Vercel deployment.

**Authority above both:** [`docs/MoveInSync-problem-statement.pdf`](../../MoveInSync-problem-statement.pdf).

**Revised 05 Sep 00:50 IST against [`docs/judge-review-2026-09-05.md`](../../judge-review-2026-09-05.md).** An adversarial judge's read of this plan against the PDF scored the *likely 17:00 state* **64/100** — a probable semifinalist, not a finalist. Tier 1 is untouched. What changed: Tier 2 is re-ordered a third time and split into three owned lanes with a **15:30 abort line**; the three PDF deliverables with no task body get one (8e diagram, **8f README**, **8g sample I/O**); 8d moves to reserve in favour of R1 + R3; Task 9 gets an owner; the OTA target becomes a named gate line; a **gated demo-video task (Task 13) is handed to Anshuman** once every earlier gate is green. Where this file and the review disagree on *what to build*, this file wins — it has already absorbed the review.

**⚠ READ [`docs/real-dataset-mapping.md`](../../real-dataset-mapping.md) FIRST.** The dataset arrived early on 2026-09-04 and is downloaded to `data/real/`. It has **five feeds, not six**, timestamps in **epoch seconds not milliseconds**, `trip_id` in **three different formats**, and **no free-text feedback at all**. Where that file and this plan disagree, that file wins — it is derived from the actual data.

**Supersedes:** [`2026-09-04-signal-desk-build.md`](2026-09-04-signal-desk-build.md) — the 24-task Java plan. Do not execute it. Read it only for the reasoning behind the carried-over decisions below.

---

## The schedule is the design constraint

| Time | Event |
|---|---|
| 10:00 | Clock starts. Dataset arrives. |
| 13:00 | **Tier 1 must be done.** If it is not, drop Tier 2 entirely and fix Tier 1. |
| 13:00–15:00 | Working lunch — keep building |
| **16:00** | **Feature freeze.** No new code. Only demo rehearsal and the deck. |
| 17:00–18:00 | Early submission window — **scored brownie points, submit at 17:00** |
| 18:00–19:30 | Semifinal, partner companies |
| 19:30–21:30 | Final jury |

**~6 hours of build time, plus ~1 hour of deck and rehearsal.** Every estimate below is against that, not against a full day.

**Tier 1 alone satisfies every mandatory requirement in the problem statement.** That is the point of the tiering: at any moment after 13:00 you have a complete, demonstrable product, and everything after widens it.

### Hard rules

- **Write the demo script before building Tier 2.** Then build only what the script needs.
- **Feature freeze at 16:00 is not negotiable.** An unpolished feature costs a fraction of what a missing deck costs.
- **Submit at 17:00.** The brownie points are free and the submission can be improved later if the window allows.
- **Keep a screenshot fallback in the deck** for every live step. The venue network is assumed hostile.
- **The scored demo runs on the laptop.** AWS URLs exist to make the deployability story real, not to be clicked live.

---

## What carries over from the retired Java build

Two tasks of the Java plan were executed before the stack changed. They are at the annotated tag `prep/java-spring-prototype`. **Three things came out of that work and it would be expensive to rediscover any of them.**

### 1. The fixture already exists — do not regenerate it

`data/fixture/*.csv` is committed: six feeds, 177,072 rows, 7.6 MB, deterministic output of a seeded generator, carrying all seven planted faults of spec §3.2 and the V07 three-week regression the demo narrative is built on.

Measured fault rates, verified by test:

| Fault | Rate |
|---|---|
| Malformed rows (extra trailing field) | 1.36% |
| Unclosed trips (no `actual_at`) | 2.29% |
| Unmatched `costs` rows | 2.78% |
| Unmatched `feedback` rows | 2.79% |
| Non-English comments | 40.55% |
| Gapped GPS traces | 11.44% |
| Orphan roster rows | 4.75% |

**Do not port the generator.** The real dataset arrives at 10:00 and replaces this as a config change; the generator's only remaining job would be regenerating a fixture nobody needs to regenerate. If you genuinely need it, `git show prep/java-spring-prototype:service/src/main/java/com/signaldesk/fixture/FixtureGenerator.java` — the two load-bearing pieces are `onTimeProbability` (the planted regression) and `FaultInjector` (the rates).

### 2. Eight spec ambiguities, already resolved — do not re-litigate

Copied forward verbatim in effect. The reasoning is in the Java plan's "Spec deviations" section.

1. **`gap = delta × reference`, so positive always means worse**, for both metric directions. Spec §6.2 says "observed − reference" and §6.3 says "delta × reference"; these have *opposite signs*. §6.3 wins. Assert it.
2. **A hard target breaches on any shortfall.** Read literally, "a TARGET missed outright → BREACH" makes WATCH and CONCERN unreachable for every target metric. Only `night_compliance` (target 100, a compliance floor) is a hard target; every other target uses the delta bands.
3. **A finding keeps every reference but takes the worst tier.** `cause` and `gap` come from the reference that produced that worst tier; ties break by declaration order.
4. **On time = within 5 minutes of schedule. An SLA breach = later than 15 minutes.** The spec names the metrics but never defines them. One constant each, one place.
5. **A trip with no `actual_at` is excluded from numerator *and* denominator.** Guessing "late" invents a fact; guessing "on time" hides one. The exclusion is counted as a null-critical field so it lowers confidence instead.
6. **The escort column is `actual_escort`** (bool, on the trip row) — MoveInSync calls it a *marshal*. There is no `marshal_required` column, so the required population is derived: dark hours plus a female rider (`emp_legs.gender`), or a `WOMAN_TRAVELLING_ALONE` alert. Without `actual_escort` that metric's coverage goes to 0 and its rule caps at `WATCH` — it degrades rather than lying.
7. **`experience` reads the comment, not just the rating.** Translation normalises `comment → comment_en`; a **deterministic Python lexicon** then scores sentiment in `{-1, 0, +1}`, and the per-response score is `clamp(rating + 0.5 × sentiment, 1, 5)`. The model does language; the arithmetic is tested Python.
8. **All hour-of-day extraction shifts by IST.** Epoch ms are absolute; "night trip" is local. `IST_OFFSET_MS = 19_800_000`.

### 3. Seven real bugs the Java build already hit — all of them stack-independent logic

These were found by a pre-flight conflict scan and by review. **Five of the seven apply to Python unchanged.** Getting them for free is the main reason last night was not wasted.

| # | Bug | Applies to Python? |
|---|---|---|
| **F1** | The generator hardcoded "S3 logout is night" while the metric SQL tested the IST hour. S3 logout sat at 06:00 IST, the `hour < 6` predicate excluded it, and **`night_compliance` matched zero rows.** Separately, S2 logout at 23:00 IST *is* night by the SQL but was marked non-night by the generator, diluting the metric toward 100%. | **YES** — the fixture is built from the fixed rule (S3 logout at 05:00 IST, S2 logout at 23:00 IST). Your night predicate must be `direction = 'logout' AND (IST hour ≥ 22 OR < 6)`. Assert it. |
| **F2** | Feeds were lazy DuckDB *views* over `read_csv_auto(store_rejects=true)`. Any later query re-scanned the CSV and re-wrote the rejects table — and the loader dropped that table before each feed, so only the last feed's rejects survived and later queries hit a missing table. | **YES, and it is the highest-risk item in ingest.** Materialise each feed as a **TABLE**, use **per-feed** rejects tables, never drop them mid-load. |
| **F3** | `coverage()` returned 0.0 when the metric's *source table* lacked the *slice* column (`feedback` has no `vendor_id`), capping every such finding at `WATCH` with cause `LOW_CONFIDENCE` — turning a modelling gap into a wall of noise. | **YES** — measure coverage unsliced when the source table lacks the slice column. Absence of the metric's *own* required column still means 0.0. |
| F4 | A transient stub between two tasks. | No — task-boundary artefact. |
| F5 | Adding a method to the model-client interface broke an eight-task-old test stub at compile time. | Softened — Python has no compile step, but a stub missing a method still fails at call time. Keep the model client's surface small. |
| F6 | The feedback normaliser was wired into a bean-factory method, so ordering was a comment rather than a fact. | **YES in spirit** — the `feedback` table must exist before normalisation runs. Make it an explicit call order in one startup function, not an import side effect. |
| F7/F8 | A view over a table of the same name (circular); a dead variable. | Minor. |

**One Java-only bug does not carry over:** `String.format("%.2f")` is locale-sensitive and broke byte-identical output on a comma-decimal locale. Python's `format()` and f-strings are locale-independent unless you explicitly opt in via the `locale` module. Do not opt in.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12**, one virtualenv at `service/.venv`, dependencies pinned in `service/requirements.txt`. No Poetry, no Conda — a lockfile argument at 10:30 costs more than it saves.
- **Node 22** for the console, pinned by `.nvmrc`; the machine's global default is deliberately 18. Run `nvm use`. Vite 8 needs 20.19+ or 22.12+, so 18 fails outright. `scripts/require-node.mjs` is the `predev` gate.
- **`ignore_errors` is forbidden** in every `read_csv_auto` call — it silently drops *valid* rows. Use `store_rejects=true` and read the rejects back.
- **The model never computes a number and never writes raw SQL.** No `run_sql` tool at any point. SQL lives only in `registry.py` and `ingest.py`; a test enforces that by grep.
- **Tiers are ordinal and never summed.** Three `WATCH`es must never outrank one `BREACH`.
- **Thresholds are measured against the real dataset, then pinned** — never invented. Land each golden assertion as "greater than zero" with the real value printed, then pin at ~80% of what was measured, recording the measurement in a comment.
- **Break-it-to-prove-it on every guard.** After a test passes, delete the behaviour it is named for, confirm the test fails, restore. See [`docs/TESTING-LESSONS.md`](../../TESTING-LESSONS.md) — that document was written from a build where **all 14 defects were in the plan, not the implementation**, and ten of them were tests that asserted nothing.
- **A test name claiming a general property** ("never", "always", "is deterministic") needs two or more data points, or it must be renamed to the single case it actually asserts.
- **Secrets in environment variables only:** `SARVAM_API_KEY`, `SLACK_WEBHOOK_URL`, `SES_FROM`, `SES_TO`, plus the AWS chain. A Slack webhook URL is itself a credential. Nothing credential-shaped reaches a commit, a screenshot, a log line, or the deck.
- **Model:** `sarvam-105b` at `https://api.sarvam.ai/v1`, `Authorization: Bearer`. Sarvam-M is deprecated and no longer served.
- **Determinism:** no wall-clock reads in the sweep path. The sweep takes an injected clock. Same dataset and same clock produce identical findings.
- **Money is integer rupees. Durations are minutes. Distances are kilometres. Timestamps are epoch milliseconds.**
- **Commit after every task.**

---

## Do tonight (4 September)

Not optional, and none of it needs the dataset. Every one of these is something that fails badly at 10:15 if left.

- [ ] `python3.12 -m venv service/.venv && service/.venv/bin/pip install -U pip`
- [ ] `service/.venv/bin/pip install "fastapi[standard]" uvicorn duckdb openai boto3 pytest httpx python-dotenv` then `pip freeze > service/requirements.txt`. **Install tonight — do not fight venue wifi at 10:05.**
- [ ] **Make something actually read `.env`.** A `.env` file is inert on its own: the code calls `os.environ.get(...)`, which does not see it. Two lines, both worth having:
  - `load_dotenv()` (from `python-dotenv`) as the first statement of the API's startup function, so `uvicorn` picks it up.
  - the same call in `service/tests/conftest.py`, so pytest and the live-API tests see the same values.

  Without this, `SARVAM_API_KEY` is `None`, the composer silently falls back to the template brief, and you spend twenty minutes tomorrow wondering why the model never runs. The fallback working correctly is exactly what makes this hard to notice.

  The shell alternative is `set -a && source .env && set +a`, which needs no dependency but has to be remembered every new terminal. Do the code version and keep the shell one for one-off scripts.
- [ ] `service/.venv/bin/python -c "import duckdb; duckdb.sql('INSTALL httpfs; LOAD httpfs;')"` — caches the extension so an S3 read cannot try to download it mid-demo.
- [ ] **Scaffold the console — it does not exist yet.** The plan's Task 7 lists files under `console/` as if the project were already there; it is not. This is a network-dependent step and must not happen at 10:05:

  ```sh
  nvm use
  npm create vite@latest console -- --template react-ts
  cd console && npm install && npm install -D vitest @testing-library/react \
      @testing-library/jest-dom @testing-library/user-event jsdom
  ```

  Then wire `console/package.json` (`"engines": {"node": ">=22.12"}`, a `predev` script running `node ../scripts/require-node.mjs`, and a `test` script running `vitest run`) and `vite.config.ts` (the react plugin, `server.proxy` mapping `/api` to `http://localhost:8080`, and `test: { environment: 'jsdom', globals: true }`). Confirm `npm run dev` serves, `npx tsc --noEmit` is clean, and `npm test` runs before you stop.

  **DONE 2026-09-04.** Two things the scaffold turned up, recorded so nobody re-discovers them:
  - `create-vite` now pulls **Vite 8 / Vitest 5 / TypeScript 6 / plugin-react 6**, not the Vite 7 this plan originally named. Same Node floor (≥20.19 or ≥22.12), so nothing breaks — but the version numbers in older text were wrong and are corrected here.
  - Putting `test: {...}` inside `vite.config.ts` needs **`/// <reference types="vitest/config" />`** at the top or `tsc` fails, and **Vitest 5 exits non-zero on zero test files** unless you set `passWithNoTests: true`. Both are in place. Confirmed running under Node v22.21.1, not the global 18.
- [ ] **Create the Slack incoming webhook** and `curl` one message to it. Minutes, no approval. This is the primary delivery channel and Tier 1 needs it.
- [ ] **Verify 2–3 team emails in SES sandbox — and note this one has human latency.** Each address gets a confirmation email that *the recipient has to click*. That is not a config step you can do at 14:00 tomorrow and have finished at 14:05; if a teammate does not check their inbox, the address stays unverified. Send the verification requests tonight and chase the clicks.

  Sandbox delivers only to verified addresses. Leaving sandbox needs SPF/DKIM/DMARC in place *before* the request can even be filed, and approval runs 4–24 h, so production SES is not achievable — sandbox-to-verified-addresses is the real email proof.

  **If SES is not configured, nothing breaks.** `slack_send` is the primary channel and `ses_send` reports `delivered=false, detail="not configured"`, which the dispatch log shows honestly. That path is tested (`test_a_channel_failure_is_recorded_and_does_not_lose_the_finding`). Email is a second delivery proof, not a dependency.
- [ ] **Fire one real Sarvam call with a `tools` array** and confirm the response carries `finish_reason: "tool_calls"`. Tool calling is the one capability the interrogation panel cannot be built without, and learning it fails at 10:00 is survivable — at 15:00 it is not. Note the credit balance while you are there.
- [ ] **Write `schemas.py` tonight** (Task 1 below). At 10:05 it should be a paste, not a debate.
- [ ] **Everyone reads [`docs/moveinsync-domain-vocabulary.md`](../../moveinsync-domain-vocabulary.md).** It is MoveInSync's own vocabulary for their own concepts, pulled from their help centre, and it corrected two things this plan had guessed wrong (the escort column is called a **marshal**, and dark hours default to **19:00–06:00**, not 22:00). The judges are MoveInSync — using their words is free credibility and using invented ones is an avoidable signal.
- [ ] **Confirm `aws sts get-caller-identity` returns something tonight.** Account access, MFA and SSO device flows are the other human-latency item: the AWS deploy (R0, the former Task 12) needs working credentials, and discovering at 13:30 that your session expired or the account needs an owner's approval costs the whole AWS story. `AWS_REGION` and the credential chain are only needed for R0 and SES — not for Tier 1.
- [ ] Set an AWS budget alarm at $50 of the $100. Credits do not stop charges by themselves.
- [ ] **Make a bare `pytest -q` work from `service/`.** Today only `PYTHONPATH=. pytest -q` passes; a bare `pytest` dies at collection with two errors, nothing documents the incantation, and the 13:00 gate line reads `pytest -q`. Two lines, committed tonight:

  ```ini
  # service/pytest.ini
  [pytest]
  pythonpath = .
  testpaths = tests
  ```

  Verify: `cd service && .venv/bin/pytest -q` → `25 passed, 1 skipped`. Commit — `chore(test): pytest.ini so a bare pytest works`. Task 8f's README then documents the command a stranger will actually type.
- [ ] Add the teammates as repo collaborators — they cannot read any of this otherwise.
- [ ] Whoever is presenting reads `PROPOSAL.md` and spec §15 tonight, not at 18:00.

---

## Work split — one developer (revised 10:05, 5 Sep)

**The team is one person.** Anshuman builds everything, using Claude Code as
the controller that dispatches one implementer subagent per task and an
independent reviewer per diff (`.superpowers/sdd/…/progress.md` is the ledger).
The three human lanes in earlier revisions are gone; what remains of them is the
*file* partition — service, console, docs — because that is what lets several
agents work at once without conflicts:

| Partition | Files | Agents may run in parallel with |
|---|---|---|
| **Service** | `service/signaldesk/`, `service/tests/` | console, docs |
| **Console** | `console/` | service, docs |
| **Docs / deploy** | `README.md`, `docs/`, `render.yaml`, `PROPOSAL.md`, deck | service, console |

Two implementers never edit the same file at once; every implementer commits
only its own files by path; every commit lands on `main`.

**Tier 1 was built overnight** (Tasks 1–7 plus follow-ups 3b, 6b/6c, 7b/7c) and
the 13:00 gate was run at 09:42 — see the ledger. **The order after Tier 1 is:**

1. Whole-branch review of Tier 1; README / architecture refresh; sample I/O (8g).
2. **Task 12R — deploy to Render** (service + console). The user's call: a public URL
   before any Tier 2 feature.
3. Tier 2 in the single-developer order below, to the 15:30 abort line.

**The Task 9 write grant is moot** — there is nobody to grant it to. Task 9 is
just the next service task.

---

## File Structure

```
service/
  requirements.txt
  .venv/                        (git-ignored)
  signaldesk/
    __init__.py
    schemas.py                  Finding, Metric, Reference, Slice, Window, FeedHealth, enums
    constants.py                grace/breach/IST/threshold constants — one place
    ingest.py                   tolerant load -> TABLES, per-feed rejects, gap register
    registry.py                 the six metric definitions; the ONLY other holder of SQL
    references.py               trend / target / peer resolution
    verdict.py                  delta, four tiers, gap sign, confidence cap, rank, audience
    decompose.py                root-cause gap attribution across dimensions   [NEW in 1.1]
    sweep.py                    the sense step + the replay clock              [NEW in 1.1]
    compose.py                  template brief, Sarvam brief, narrative validator
    delivery.py                 Slack webhook, SES email, dispatch log
    model.py                    Sarvam client, token/cost accounting            [NEW in 1.1]
    tools.py                    the four validated tools + the interrogator
    api.py                      FastAPI app: all endpoints
  tests/
    test_ingest.py  test_registry.py  test_references.py  test_verdict.py
    test_decompose.py  test_sweep.py  test_compose.py  test_delivery.py
    test_tools.py  test_invariant.py
console/
  package.json  vite.config.ts  tsconfig.json  index.html
  src/main.tsx  App.tsx  api/client.ts  api/types.ts
  src/components/  FindingsList.tsx  FindingRow.tsx  EvidencePanel.tsx
                   TierBadge.tsx  FeedHealthStrip.tsx  BriefPreview.tsx
                   CostMeter.tsx           [NEW in 1.1]
                   ReplayControls.tsx      [NEW in 1.1]
                   CauseBreakdown.tsx      [NEW in 1.1]
                   InterrogationPanel.tsx  ToolTrace.tsx
data/fixture/*.csv              committed; replaced by the real dataset at 10:00
data/real/                      the provided dataset lands here (git-ignored if large)
infra/
  Dockerfile                    the service, for App Runner
  apprunner.yaml
  README.md                     the exact AWS steps, so they are repeatable
```

**Why these boundaries:** `registry.py` and `ingest.py` are the only modules holding SQL, which makes the §1.1 invariant checkable by grep rather than by review. `verdict.py` and `decompose.py` have no I/O and no clock, so they are pure-unit-testable — the property the whole trustworthiness argument rests on. `model.py` is the only module that talks to Sarvam.

---

# TIER 1 — the mandatory bar (target: complete by 13:00)

**Tier 1 alone satisfies every mandatory requirement in the problem statement:** a working prototype on the provided dataset, a loop that senses/reasons/acts rather than answering queries, a named persona, and every metric contextualised against a reference point.

**The 13:00 target is only reachable with the work split.** The critical path is Tasks 2 → 3 → 4 → 5 (~2h50, one person). Tasks 6 and 7 run **in parallel against hardcoded fake findings from minute one** — Task 1's contracts are what make that possible. If everyone waits for real data, Tier 1 lands at 15:00 and Tier 2 never happens.

---

### Task 1: The two contracts (do this TONIGHT — ~25 min)

**Files:** `service/signaldesk/schemas.py`, `service/signaldesk/constants.py`, `service/tests/test_schemas.py`

**Interfaces produced:** everything downstream. Agree these at 10:05 and do not renegotiate at 12:00.

This is the task that lets three people work at once. It carries five of the eight resolved spec ambiguities directly in code.

- [ ] **Step 1: Write `constants.py`**

```python
"""The thresholds the spec names its metrics for but never defines.

One place, so the real dataset can move them in one edit at 10:30.
"""

# Deviation 4: the spec names on-time arrival and SLA breach but defines neither.
ON_TIME_GRACE_MS = 5 * 60_000
SLA_BREACH_MS = 15 * 60_000

# Deviation 8: epoch ms are absolute; "night trip" is local.
IST_OFFSET_MS = 19_800_000

# MoveInSync calls this window "dark hours" and configures it PER CITY. Their
# published example is 19:00-06:00, so 19 is the default here — an earlier draft
# guessed 22:00 and was three hours too narrow. Per-site override is the honest
# multi-tenancy story and is nearly free, since it is already one dict.
# See docs/moveinsync-domain-vocabulary.md §1.
DARK_HOURS_DEFAULT = (19, 6)
DARK_HOURS_BY_SITE: dict[str, tuple[int, int]] = {}


def dark_hours(site: str | None = None) -> tuple[int, int]:
    return DARK_HOURS_BY_SITE.get(site or "", DARK_HOURS_DEFAULT)

# Verdict bands, as a fraction of the reference. PROVISIONAL until Task 5
# measures them against the real dataset (spec §6.3 requires this).
PASS_MAX = 0.02
WATCH_MAX = 0.05
CONCERN_MAX = 0.15

# Below this, no tier above WATCH may be emitted.
MIN_TRUSTED_CONFIDENCE = 0.5
# Below this, the narrative must disclose the uncertainty.
DISCLOSE_CONFIDENCE_BELOW = 0.9

# Sarvam pricing for the cost meter.
#
# MEASURED 2026-09-04 from the Sarvam dashboard: 629 tokens billed at Rs 0.03,
# i.e. ~Rs 0.048 per 1k tokens blended (~Rs 48 per million).
#
# Two honest caveats that belong on the slide, not just in this comment:
#   1. Rs 0.03 is the dashboard's rounded display, so the true rate is somewhere
#      in Rs 0.040-0.056 per 1k. That is +/-17%, which is fine for "fractions of
#      a rupee" and NOT fine for quoting three significant figures.
#   2. It is a BLENDED rate. We do not have the input/output split, so both
#      constants below carry the same value. If Sarvam publishes separate
#      figures, use those instead of this measurement.
INR_PER_1K_INPUT_TOKENS = 0.048
INR_PER_1K_OUTPUT_TOKENS = 0.048
EMPLOYEES_AT_SCALE = 5_000

# Reasoning tokens ARE billed even when content comes back empty -- the 629
# tokens above were spent on three calls that returned nothing, truncated by a
# max_tokens that was too low. If the API reports reasoning tokens separately,
# the cost meter must add them, or it will under-report.
COUNT_REASONING_TOKENS = True
```

- [ ] **Step 2: Write `schemas.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from . import constants


class Tier(Enum):
    """Ordered, compared ordinally, NEVER summed into a score. Summing would let
    three mild issues outrank one genuine breach."""
    PASS = 0
    WATCH = 1
    CONCERN = 2
    BREACH = 3

    def __lt__(self, other: "Tier") -> bool:
        return self.value < other.value


class Direction(Enum):
    HIGHER = "HIGHER"
    LOWER = "LOWER"


class ReferenceKind(Enum):
    TREND = "TREND"
    TARGET = "TARGET"
    PEER = "PEER"


class Cause(Enum):
    ON_REFERENCE = "ON_REFERENCE"      # a PASS carries no accusatory cause
    BELOW_TARGET = "BELOW_TARGET"
    TREND_REGRESSION = "TREND_REGRESSION"
    PEER_LAGGARD = "PEER_LAGGARD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    DATA_GAP = "DATA_GAP"


class Audience(Enum):
    TRANSPORT_MANAGER = "TRANSPORT_MANAGER"
    FACILITIES_HEAD = "FACILITIES_HEAD"
    LINE_MANAGER = "LINE_MANAGER"


class Dimension(Enum):
    """The enumerated slice dimensions. The model selects from these; it never
    composes a join. These column names are the only ones that reach SQL —
    values are always bound as parameters."""
    VENDOR = "t.vendor_id"
    SITE = "t.site_id"
    SHIFT = "t.shift"
    MODE = "t.mode"
    DIRECTION = "t.direction"
    NONE = ""

    @property
    def column(self) -> str:
        if self is Dimension.NONE:
            raise ValueError("Dimension.NONE has no column")
        return self.value

    @classmethod
    def parse(cls, raw: str) -> "Dimension":
        for d in cls:
            if d.name.lower() == (raw or "").lower():
                return d
        valid = ", ".join(d.name for d in cls)
        raise ValueError(f"unknown dimension {raw!r}; valid values are {valid}")


@dataclass(frozen=True)
class Slice:
    dim: Dimension
    value: Optional[str] = None

    def __post_init__(self):
        if self.dim is Dimension.NONE and self.value is not None:
            raise ValueError("Dimension.NONE must carry a null value")
        if self.dim is not Dimension.NONE and not self.value:
            raise ValueError(f"dimension {self.dim.name} requires a value")

    @staticmethod
    def all() -> "Slice":
        return Slice(Dimension.NONE, None)

    @property
    def label(self) -> str:
        return "overall" if self.dim is Dimension.NONE else f"{self.dim.name.lower()} {self.value}"


WEEK_MS = 7 * 86_400_000


@dataclass(frozen=True)
class Window:
    """Half-open: [start_ms, end_ms)."""
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("window end must be after start")

    @staticmethod
    def week_ending(end_ms: int) -> "Window":
        return Window(end_ms - WEEK_MS, end_ms)

    # The real dataset covers MAY-JULY 2026. Point the simulated clock at the end
    # of July, not the fixture's September window -- a sweep over an empty window
    # emits one DATA_GAP finding and nothing else, which looks like an engine bug.
    # 2026-08-01T00:00:00Z in epoch ms:
    REAL_DATA_END_MS = 1_785_542_400_000

    def shifted_back(self, n: int) -> "Window":
        length = self.end_ms - self.start_ms
        new_end = self.end_ms - n * length
        return Window(new_end - length, new_end)

    @property
    def label(self) -> str:
        import datetime as _dt
        fmt = lambda ms: _dt.datetime.fromtimestamp(ms / 1000, _dt.UTC).strftime("%Y-%m-%d")
        return f"{fmt(self.start_ms)}..{fmt(self.end_ms - 1)}"


@dataclass(frozen=True)
class Reference:
    kind: ReferenceKind
    value: float
    label: str


@dataclass(frozen=True)
class Metric:
    """The SQL here is the ONLY SQL outside ingest.py: nothing else queries raw
    tables. It must aggregate to exactly one number, bind the window as two
    parameters in order, and contain the token {{SLICE}}."""
    id: str
    label: str
    unit: str
    better: Direction
    sql: str
    refs: tuple[ReferenceKind, ...]
    source: str                       # the feed/table the confidence comes from
    required_columns: tuple[str, ...]
    target: Optional[float] = None
    hard_target: bool = False         # deviation 2: breaches on ANY shortfall

    def __post_init__(self):
        declares = ReferenceKind.TARGET in self.refs
        if declares and self.target is None:
            raise ValueError(f"metric {self.id} declares TARGET but has no target value")
        if not declares and self.target is not None:
            raise ValueError(f"metric {self.id} has a target but does not declare TARGET")
        if self.hard_target and self.target is None:
            raise ValueError(f"metric {self.id} has a hard target but no target value")
        if "{{SLICE}}" not in self.sql:
            raise ValueError(f"metric {self.id} SQL has no {{{{SLICE}}}} token")


@dataclass(frozen=True)
class FeedHealth:
    feed: str
    rows_loaded: int
    rows_rejected: int
    unmatched_keys: int
    null_critical_fields: int
    confidence: float

    @staticmethod
    def of(feed, rows_loaded, rows_rejected, unmatched_keys, null_critical_fields) -> "FeedHealth":
        considered = rows_loaded + rows_rejected
        raw = 1.0 if considered == 0 else 1.0 - (
            rows_rejected + unmatched_keys + null_critical_fields) / considered
        return FeedHealth(feed, rows_loaded, rows_rejected, unmatched_keys,
                          null_critical_fields, max(0.0, min(1.0, raw)))

    @property
    def must_be_disclosed(self) -> bool:
        return self.confidence < constants.DISCLOSE_CONFIDENCE_BELOW


@dataclass(frozen=True)
class Finding:
    """The unit of everything downstream: the console renders it, the narrative
    is written from it, delivery routes on it.

    Deviation 1: gap is delta x reference, so POSITIVE ALWAYS MEANS WORSE, for
    both metric directions, and the sign agrees with the tier by construction.
    Spec §6.2's "observed - reference" wording is superseded by §6.3.

    evidence_sql is not decoration. It is the answer to "where did this number
    come from", as a query the reader can run rather than a claim.
    """
    id: str
    metric_id: str
    slice: Slice
    window: Window
    observed: float
    refs: tuple[Reference, ...]
    tier: Tier
    cause: Cause
    gap: float
    confidence: float
    audiences: frozenset[Audience]
    evidence_sql: str

    def __post_init__(self):
        if self.tier is Tier.PASS and self.gap > 0:
            raise ValueError(
                f"finding {self.id} is a PASS carrying a positive (worse-than-reference) gap")

    @property
    def must_disclose_confidence(self) -> bool:
        return self.confidence < constants.DISCLOSE_CONFIDENCE_BELOW


def finding_id(metric_id: str, slc: Slice, window: Window) -> str:
    """Stable across runs, so a finding can be re-opened by URL and re-explained."""
    import hashlib
    material = "|".join([metric_id, slc.dim.name, slc.value or "",
                         str(window.start_ms), str(window.end_ms)])
    return hashlib.sha256(material.encode()).hexdigest()[:12]
```

- [ ] **Step 3: Write the contract tests**

`service/tests/test_schemas.py`:

```python
import pytest

from signaldesk.schemas import (Audience, Cause, Dimension, Direction, Finding,
                                Metric, Reference, ReferenceKind, Slice, Tier,
                                Window, finding_id)


def test_tiers_compare_ordinally_and_a_breach_beats_any_watch():
    assert Tier.BREACH > Tier.CONCERN > Tier.WATCH > Tier.PASS
    assert max([Tier.WATCH, Tier.WATCH, Tier.WATCH, Tier.BREACH]) is Tier.BREACH


def test_an_unknown_dimension_is_refused_with_the_valid_values_named():
    with pytest.raises(ValueError, match="route"):
        Dimension.parse("route")
    with pytest.raises(ValueError, match="VENDOR"):
        Dimension.parse("route")


def test_a_slice_must_agree_with_its_dimension():
    assert Slice.all().label == "overall"
    assert Slice(Dimension.VENDOR, "V07").label == "vendor V07"
    with pytest.raises(ValueError):
        Slice(Dimension.VENDOR, None)
    with pytest.raises(ValueError):
        Slice(Dimension.NONE, "V07")


def test_trend_windows_are_the_four_preceding_ones_and_exclude_the_evaluated_window():
    w = Window.week_ending(10 * 7 * 86_400_000)
    assert w.shifted_back(1).end_ms == w.start_ms
    assert w.shifted_back(4).start_ms == w.start_ms - 4 * (w.end_ms - w.start_ms)


def test_a_metric_declaring_a_target_must_have_one_and_vice_versa():
    with pytest.raises(ValueError, match="TARGET"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1 {{SLICE}}",
               (ReferenceKind.TREND,), "trips", (), target=90.0)
    with pytest.raises(ValueError, match="TARGET"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1 {{SLICE}}",
               (ReferenceKind.TARGET,), "trips", ())


def test_a_metric_without_a_slice_token_is_refused():
    with pytest.raises(ValueError, match="SLICE"):
        Metric("bad", "Bad", "%", Direction.HIGHER, "SELECT 1",
               (ReferenceKind.TREND,), "trips", ())


def _finding(tier, gap):
    w = Window.week_ending(10 * 7 * 86_400_000)
    return Finding("f1", "ota", Slice.all(), w, 78.0,
                   (Reference(ReferenceKind.TARGET, 90.0, "SLA target"),),
                   tier, Cause.BELOW_TARGET, gap, 0.97,
                   frozenset({Audience.TRANSPORT_MANAGER}), "SELECT 1")


def test_a_pass_cannot_be_constructed_with_a_worse_than_reference_gap():
    # A sign-flipped gap produces a confidently wrong sentence, so it is made
    # impossible to construct rather than merely unlikely.
    _finding(Tier.PASS, -1.0)
    _finding(Tier.BREACH, 12.0)
    with pytest.raises(ValueError, match="PASS"):
        _finding(Tier.PASS, 12.0)


def test_finding_ids_are_stable_across_calls_and_distinct_across_slices():
    w = Window.week_ending(10 * 7 * 86_400_000)
    assert finding_id("ota", Slice.all(), w) == finding_id("ota", Slice.all(), w)
    assert finding_id("ota", Slice.all(), w) != finding_id(
        "ota", Slice(Dimension.VENDOR, "V07"), w)
    assert finding_id("ota", Slice.all(), w) != finding_id("sla_breach", Slice.all(), w)


def test_confidence_disclosure_threshold_is_nine_tenths():
    assert _finding(Tier.BREACH, 12.0).must_disclose_confidence is False
    w = Window.week_ending(10 * 7 * 86_400_000)
    low = Finding("f2", "ota", Slice.all(), w, 78.0, (), Tier.WATCH,
                  Cause.LOW_CONFIDENCE, 12.0, 0.62,
                  frozenset({Audience.TRANSPORT_MANAGER}), "SELECT 1")
    assert low.must_disclose_confidence is True
```

- [ ] **Step 4: Run them**

Run: `cd service && .venv/bin/python -m pytest tests/test_schemas.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Break-it-to-prove-it**

Delete the `tier is Tier.PASS and gap > 0` check in `Finding.__post_init__`, rerun. Expected: `test_a_pass_cannot_be_constructed_with_a_worse_than_reference_gap` FAILS. Restore.

Change `Dimension.parse` to return `Dimension.NONE` on an unknown value instead of raising, rerun. Expected: the unknown-dimension test FAILS. Restore. That guard is what stops the model's tool arguments reaching SQL unvalidated.

- [ ] **Step 6: Commit**

```bash
git add service && git commit -m "feat(schemas): the two contracts — Finding and Metric — with the resolved spec deviations encoded"
```

---

### Task 2: Tolerant ingest, rejects quarantine, gap register (~45 min, critical path)

**Files:** `service/signaldesk/ingest.py`, `service/tests/test_ingest.py`

**Interfaces produced:** `load_all(con, source) -> dict[str, FeedHealth]`, `FEEDS`, `rejects(con, feed)`, `source_for(path_or_s3)`.

**This task carries bug F2, which is the highest-risk item in the whole build.** Read F2 in the carry-over section before writing a line.

- [ ] **Step 1: Write the failing tests**

```python
import duckdb
import pytest

from signaldesk import ingest


@pytest.fixture
def con():
    c = duckdb.connect()
    yield c
    c.close()


def test_a_malformed_row_is_quarantined_and_counted_rather_than_dropped(con, tmp_path):
    (tmp_path / "trips.csv").write_text(
        "trip_id,vendor_id,scheduled_at\n"
        "T1,V01,100\n"
        "T2,V01,200,UNEXPECTED_EXTRA_FIELD\n"
        "T3,V02,300\n"
    )
    health = ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))

    assert health.rows_loaded == 2, "the two good rows survive"
    assert health.rows_rejected == 1, "the bad row is counted, not silently lost"
    assert len(ingest.rejects(con, "trips")) == 1
    assert ingest.rejects(con, "trips")[0]["line"] == 3


def test_union_by_name_merges_two_files_with_different_column_sets(con, tmp_path):
    (tmp_path / "trips_a.csv").write_text("trip_id,vendor_id\nT1,V01\n")
    (tmp_path / "trips_b.csv").write_text("trip_id,site_id\nT2,SITE1\n")

    ingest.load_feed(con, "trips", str(tmp_path / "trips_*.csv"))

    row = con.sql("SELECT count(*) n, count(vendor_id) v, count(site_id) s FROM trips").fetchone()
    assert row == (2, 1, 1)


def test_a_second_query_does_not_rescan_the_csv_or_double_count_rejects(con, tmp_path):
    # BUG F2. A lazy view over read_csv_auto(store_rejects=true) re-scans on every
    # query and re-appends to the rejects table. Every metric query would do that.
    (tmp_path / "trips.csv").write_text(
        "trip_id,vendor_id\nT1,V01\nT2,V01,EXTRA\n")
    health = ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))

    con.sql("SELECT count(*) FROM trips").fetchone()
    con.sql("SELECT count(*) FROM trips").fetchone()

    assert len(ingest.rejects(con, "trips")) == health.rows_rejected
    assert con.sql("SELECT count(*) FROM reject_errors_trips").fetchone()[0] == 1


def test_each_feed_keeps_its_own_rejects(con, tmp_path):
    # BUG F2, second half: one shared rejects table left only the last feed's rows.
    (tmp_path / "trips.csv").write_text("trip_id\nT1\nT2,EXTRA\n")
    (tmp_path / "costs.csv").write_text("trip_id,total_inr\nT1,300\nT2,310,EXTRA\n")

    ingest.load_feed(con, "trips", str(tmp_path / "trips.csv"))
    ingest.load_feed(con, "costs", str(tmp_path / "costs.csv"))

    assert len(ingest.rejects(con, "trips")) == 1, "not clobbered by the costs load"
    assert len(ingest.rejects(con, "costs")) == 1


def test_confidence_is_exactly_one_on_clean_input_and_falls_on_each_fault(con, tmp_path):
    from signaldesk.schemas import FeedHealth
    assert FeedHealth.of("costs", 2, 0, 0, 0).confidence == 1.0
    assert FeedHealth.of("costs", 2, 0, 1, 0).confidence == 0.5   # unmatched
    assert FeedHealth.of("costs", 1, 1, 0, 0).confidence == 0.5   # rejected
    assert FeedHealth.of("costs", 1, 0, 0, 1).confidence == 0.0   # null critical
    assert FeedHealth.of("costs", 1, 0, 5, 0).confidence == 0.0   # clamped, not negative


def test_no_call_uses_ignore_errors():
    # A grep-as-a-test: ignore_errors silently drops VALID rows, and no
    # behavioural test would catch a future edit adding it.
    import pathlib
    src = pathlib.Path(ingest.__file__).read_text()
    assert "ignore_errors" not in src
```

- [ ] **Step 2: Run to verify failure**

Run: `cd service && .venv/bin/python -m pytest tests/test_ingest.py -q`
Expected: FAIL — `AttributeError: module 'signaldesk.ingest' has no attribute 'load_feed'`.

- [ ] **Step 3: Write `ingest.py`**

```python
"""Tolerant load. Loud about what it cannot read.

ignore_errors is FORBIDDEN: it has a known defect where it silently drops VALID
rows, and silent loss is the opposite of what this product claims. store_rejects
keeps every failure inspectable.
"""
from __future__ import annotations

import duckdb

from .schemas import FeedHealth

# The five REAL feeds. There is no gps_pings file and no delays file -- delay is
# a COLUMN on the trip row. See docs/real-dataset-mapping.md §1.
# Note the space in the trip filenames: "Ride_data _trip-may_2026.csv".
FEEDS = ("trips", "emp_legs", "feedback", "bill", "alerts")

GLOBS = {
    "trips":    "Ride_data*trip-*.csv",   # three monthly files, union_by_name
    "emp_legs": "emp_Data.csv",
    "feedback": "trip_feedback.csv",
    "bill":     "bill_data.csv",
    "alerts":   "alerts_data.csv",
}

# Critical columns per feed, in the REAL schema. actual_escort is deliberately
# absent: a dataset without it must degrade marshal_compliance, not the on-time
# figures. Per-metric coverage in registry.py handles that instead.
CRITICAL = {
    "trips":    ("trip_id", "vendor_id", "planned_start_epoch", "actual_end_epoch"),
    "emp_legs": ("trip_id", "stwid"),
    "feedback": ("trip_id", "route_rating"),
    # trip_id is NOT always a trip id in bill: 160 rows hold the literal string
    # 'OverHead' -- Rs 44.6 lakh of vendor charges belonging to no trip. Counting
    # them as critically incomplete is honest: they are real money we cannot
    # attribute, and that is itself worth reporting.
    "bill":     ("trip_id", "trip_cost"),
    "alerts":   ("trip_id", "event_type"),
}

# Every feed hangs off trips.trip_id. Run these AFTER normalisation, or they
# report ~100% unmatched because the three id formats never compare equal.
UNMATCHED_SQL = {
    "emp_legs": "SELECT count(*) FROM emp_legs WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "feedback": "SELECT count(*) FROM feedback WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "bill":     "SELECT count(*) FROM bill     WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
    "alerts":   "SELECT count(*) FROM alerts   WHERE trip_id NOT IN (SELECT trip_id FROM trips)",
}


def source_for(base: str) -> callable:
    """The engine's whole knowledge of where data lives. A local directory on the
    day, an s3:// prefix in production — the query is identical either way, which
    is what makes the deployment story an adapter swap rather than a rewrite."""
    base = base.rstrip("/")
    return lambda feed: f"{base}/{feed}.csv"


def load_feed(con: duckdb.DuckDBPyConnection, feed: str, glob: str) -> FeedHealth:
    """Scan once through a tolerant reader, then materialise as a TABLE.

    BUG F2 — why a table and not a view: a view over read_csv_auto(store_rejects)
    is lazy, so every later query re-scans the file and re-appends to the rejects
    table. Every metric query does that. Materialising costs one pass and makes
    the reject count a fact rather than a moving number.
    """
    errors, scans = f"reject_errors_{feed}", f"reject_scans_{feed}"
    con.execute(f"DROP TABLE IF EXISTS {errors}")
    con.execute(f"DROP TABLE IF EXISTS {scans}")

    # The glob is interpolated, not bound: read_csv_auto's first argument is not
    # parameterisable. It comes from source_for(), never from a user or the model,
    # and the four tools expose no path to this function at all.
    safe = glob.replace("'", "''")
    con.execute(f"""
        CREATE OR REPLACE TABLE {feed} AS
        SELECT * FROM read_csv_auto(
          '{safe}',
          union_by_name = true,
          store_rejects = true,
          rejects_table = '{errors}',
          rejects_scan  = '{scans}'
        )
    """)

    rows_loaded = con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0]
    return FeedHealth.of(feed, rows_loaded, len(rejects(con, feed)),
                         _unmatched(con, feed), _null_critical(con, feed))


def load_all(con: duckdb.DuckDBPyConnection, source) -> dict[str, FeedHealth]:
    """Load order matters: the referential checks read trips and feedback, so
    those must exist first. Two passes rather than one clever ordering."""
    for feed in FEEDS:
        load_feed(con, feed, source(feed))
    # Second pass: recompute health now that every table exists, so the
    # referential counts are real rather than zero-because-absent.
    return {feed: FeedHealth.of(feed,
                                con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0],
                                len(rejects(con, feed)),
                                _unmatched(con, feed),
                                _null_critical(con, feed))
            for feed in FEEDS}


def rejects(con: duckdb.DuckDBPyConnection, feed: str) -> list[dict]:
    """A quarantined row is a finding, not a log line."""
    table = f"reject_errors_{feed}"
    try:
        rows = con.sql(f"""
            SELECT line, coalesce(column_name, '') AS column_name,
                   coalesce(error_message, '') AS error_message,
                   coalesce(csv_line, '') AS csv_line
            FROM {table}
        """).fetchall()
    except duckdb.CatalogException:
        return []   # DuckDB only creates the table when there is a reject
    return [{"line": r[0], "column": r[1], "error": r[2], "raw": r[3]} for r in rows]


def _present_columns(con, table: str) -> set[str]:
    return {r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()}


def _unmatched(con, feed: str) -> int:
    sql = UNMATCHED_SQL.get(feed)
    if not sql:
        return 0
    try:
        return con.sql(sql).fetchone()[0]
    except duckdb.Error:
        return 0    # a referenced table not loaded yet; the second pass fixes it


def _null_critical(con, feed: str) -> int:
    cols = CRITICAL.get(feed, ())
    if not cols:
        return 0
    present = _present_columns(con, feed)
    missing = [c for c in cols if c not in present]
    rows = con.sql(f"SELECT count(*) FROM {feed}").fetchone()[0]
    if missing:
        # A critical column absent from the dataset entirely: every row is
        # critically incomplete, and the confidence figure should say so.
        return rows
    predicate = " OR ".join(f"{c} IS NULL" for c in cols)
    return con.sql(f"SELECT count(*) FROM {feed} WHERE {predicate}").fetchone()[0]
```

- [ ] **Step 3b: Normalise at the ingest boundary — do this before anything else**

Three things in the real data will silently produce zero rows or wrong numbers if
they reach the registry unchanged. Fix all three **once**, here, so no downstream
layer has to know:

```python
# One view per feed, over the materialised table, presenting the names and units
# the registry expects. Everything below is a documented quirk from
# data/real/Dictionary/README.md -- not defensive guessing.
NORMALISE = {
    "trips": """
        CREATE OR REPLACE VIEW trips AS SELECT
          business_unit,
          office                AS site_id,
          product_type          AS mode,
          shift_type,
          -- trip_id is "1,097,076" here, "1123974" in bill, int64 in emp_legs.
          -- Every join returns ZERO ROWS unless all three are normalised.
          CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          trip_direction,
          vendor_id,
          actual_escort,
          -- Epoch SECONDS in the source. Multiply to ms so the schemas, the
          -- windows and the verdict engine keep working in the unit they were
          -- written for. See mapping doc §2.
          CAST(REPLACE(CAST(planned_start_epoch AS VARCHAR), ',', '') AS BIGINT) * 1000 AS scheduled_at,
          CAST(REPLACE(CAST(actual_end_epoch   AS VARCHAR), ',', '') AS BIGINT) * 1000 AS actual_at,
          delay_reason,
          CAST(REPLACE(CAST(delay_minutes AS VARCHAR), ',', '') AS BIGINT) AS delay_minutes,
          is_driver_nc, is_cab_nc,
          planned_km, traveled_km, actual_cab_capacity,
          plannedemployee_cnt, actualemployee_cnt, noshow_cnt,
          actual_cab_fuel_type, trip_nodal
        FROM trips_raw
    """,
    "bill": """
        CREATE OR REPLACE VIEW bill AS SELECT
          business_unit, office AS site_id,
          vendor AS vendor_id,          -- called `vendor` here, `vendor_id` in trips
          CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          contract, slab_name,
          total_trip_km,
          CAST(REPLACE(CAST(trip_cost AS VARCHAR), ',', '') AS BIGINT) AS trip_cost
        FROM bill_raw
    """,
    "feedback": """
        CREATE OR REPLACE VIEW feedback AS SELECT
          business_unit,
          CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          trip_type AS trip_direction,  -- different name in this file
          CAST(REPLACE(CAST(stwid AS VARCHAR), ',', '') AS BIGINT) AS stwid,
          route_rating, driver_rating, cab_rating, safety_rating, marshal_rating
        FROM feedback_raw
    """,
    # emp_legs already has clean int64 keys -- the ONE file that does.
    # Negative planned_km/traveled_km are physically impossible (down to -6.63);
    # NULL them so the gap register counts them and confidence falls, rather
    # than letting them poison an average.
    "emp_legs": """
        CREATE OR REPLACE VIEW emp_legs AS SELECT
          business_unit, office AS site_id, product_type AS mode, shift_type,
          trip_id, stwid, gender, signintype, boarding_status,
          not_boarding_reason, is_no_show,
          CAST(planned_pickup_epoch AS BIGINT) * 1000 AS planned_pickup_at,
          CAST(actual_pickup_epoch  AS BIGINT) * 1000 AS actual_pickup_at,
          CASE WHEN planned_km  < 0 THEN NULL ELSE planned_km  END AS planned_km,
          CASE WHEN traveled_km < 0 THEN NULL ELSE traveled_km END AS traveled_km
        FROM emp_legs_raw
        WHERE stwid <> 0             -- 0 is a placeholder, not a rider
    """,
    "alerts": """
        CREATE OR REPLACE VIEW alerts AS SELECT
          business_unit,
          CAST(REPLACE(CAST(trip_id AS VARCHAR), ',', '') AS BIGINT) AS trip_id,
          CAST(REPLACE(CAST(stwid   AS VARCHAR), ',', '') AS BIGINT) AS stwid,
          event_id, event_type, state_text, source,
          -- severity carries a stray literal "False" outside the enum
          CASE WHEN severity IN ('Sev-1','Sev-2','Sev-3') THEN severity END AS severity
        FROM alerts_raw
    """,
}
```

Load each CSV to `<feed>_raw`, then create the normalised view. Tests to add:

```
trip_id normalises to the same integer from all three source formats
epochs come out in milliseconds, not seconds
a negative planned_km becomes null rather than a negative average
the stray "False" severity becomes null, not a fourth severity level
stwid = 0 rows are excluded
joining trips to bill on the normalised key returns more than zero rows
```

**That last test is the one that matters.** Un-normalised, every join silently
returns nothing and every metric reports a `DATA_GAP` — which looks exactly like
an engine bug and is not one.

- [ ] **Step 4: Run the tests**

Run: `cd service && .venv/bin/python -m pytest tests/test_ingest.py -q`
Expected: PASS.

The rejects-table column names vary across DuckDB versions. If the projection fails, run a rejecting load then `DESCRIBE reject_errors_trips` and correct it. Do not fall back to `SELECT *` with positional indexes.

- [ ] **Step 5: Point it at the real dataset and print what it found**

```python
**One thing to expect in the real data that the fixture does not model.**
MoveInSync's own definition: *"In cases of GPS loss the actual Km will not be
calculated."* So GPS gaps and missing distances are **correlated**, not
independent — a trip with a GPS hole is a trip whose actual distance was never
computed. Our fixture plants those as two separate faults. When the real data
arrives, check whether `actual_km` nulls cluster on the GPS-gap trips, and if
they do, **say so in the data-quality panel**: one causal story reads far better
than two unrelated defect rates. Their `auto sign-off` feature is likewise the
explanation for trips with no close-out time.
```

```python
def test_the_real_dataset_loads_and_its_health_is_printed():
    import os, pathlib, duckdb
    from signaldesk import ingest
    base = os.environ.get("SIGNALDESK_DATA", "../data/fixture")
    if not pathlib.Path(base).is_dir():
        import pytest; pytest.skip(f"no dataset at {base}")
    con = duckdb.connect()
    health = ingest.load_all(con, ingest.source_for(base))
    for h in health.values():
        print(f"MEASURED {h.feed} loaded={h.rows_loaded} rejected={h.rows_rejected} "
              f"unmatched={h.unmatched_keys} nullCritical={h.null_critical_fields} "
              f"confidence={h.confidence:.4f}")
    assert all(0.0 <= h.confidence <= 1.0 for h in health.values())
    assert health["trips"].rows_loaded > 0
```


Run it against the committed fixture now, and **again at 10:05 against the real dataset** with `SIGNALDESK_DATA=../data/real`. Record both. **At least one feed should land below 0.9** so the disclosure path has something to disclose; if none does on the real data, say so on stage rather than inventing a fault.

- [ ] **Step 6: Break-it-to-prove-it**

Change `CREATE OR REPLACE TABLE` to `CREATE OR REPLACE VIEW`, rerun. Expected: `test_a_second_query_does_not_rescan_the_csv_or_double_count_rejects` FAILS — that is bug F2 reproducing. Restore.

Point both loads at one shared `reject_errors` table, rerun. Expected: `test_each_feed_keeps_its_own_rejects` FAILS. Restore.

Remove `union_by_name = true`, rerun. Expected: the union test FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
git add service && git commit -m "feat(ingest): tolerant DuckDB load into tables, per-feed rejects, gap register"
```

---
### Task 3: The metric registry (~50 min, critical path)

**Files:** `service/signaldesk/registry.py`, `service/tests/test_registry.py`

**Interfaces produced:** `METRICS`, `by_id(id)`, `active(ids)`, `evaluate(con, metric, slice, window) -> float | None`, `coverage(con, metric, slice, window) -> float`, `distinct_values(con, dim, window)`, `evidence_sql(metric, slice, window)`.

All six metrics are **defined** here; only three are **active** in Tier 1. Adding the other three later costs minutes because the shape is already right. `experience` needs Task 11's normalised feedback table, so its SQL test skips until then.

- [ ] **Step 1: Write the six definitions**

```python
"""The governed vocabulary. NOTHING ELSE queries raw tables."""
from __future__ import annotations

import duckdb

from . import constants as C
from .schemas import Dimension, Direction, Metric, ReferenceKind, Slice, Window

# Deviation 5: a trip with no actual_at is excluded from numerator AND
# denominator. Guessing "late" invents a fact; guessing "on time" hides one.
_OTA_SQL = f"""
SELECT 100.0 * sum(CASE WHEN t.actual_at <= t.scheduled_at + {C.ON_TIME_GRACE_MS} THEN 1 ELSE 0 END)
       / nullif(count(*), 0)
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND t.actual_at IS NOT NULL
  {{{{SLICE}}}}
"""

_SLA_SQL = f"""
SELECT 100.0 * sum(CASE WHEN t.actual_at > t.scheduled_at + {C.SLA_BREACH_MS} THEN 1 ELSE 0 END)
       / nullif(count(*), 0)
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND t.actual_at IS NOT NULL
  {{{{SLICE}}}}
"""

_COST_SQL = """
SELECT avg(c.total_inr)
FROM costs c JOIN trips t ON t.trip_id = c.trip_id
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  {{SLICE}}
"""

# MoveInSync's term is MARSHAL, not "night escort", and the window is "dark
# hours" — configured per city, default 19:00-06:00. See
# docs/moveinsync-domain-vocabulary.md §1. Their model has THREE states
# (Required / Maybe Required / Good to go), so the honest figure is
# "signed in WHERE required", with Maybe-Required excluded from the denominator
# rather than flattened into a boolean.
#
# BUG F1 still applies: the predicate is the IST HOUR, not a shift name. An
# earlier draft hardcoded "S3 logout" against an hour predicate and the metric
# matched ZERO rows. Assert the population is non-empty.
_DARK_START, _DARK_END = C.dark_hours()
_MARSHAL_SQL = f"""
SELECT 100.0 * sum(CASE WHEN t.marshal_signed_in THEN 1 ELSE 0 END) / nullif(count(*), 0)
FROM trips t
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  AND t.marshal_required
  AND (extract(hour FROM epoch_ms(t.scheduled_at + {C.IST_OFFSET_MS})) >= {_DARK_START}
       OR extract(hour FROM epoch_ms(t.scheduled_at + {C.IST_OFFSET_MS})) < {_DARK_END})
  {{{{SLICE}}}}
"""

# The real column is `actual_escort` (bool). There is no marshal_required
# column, so the required POPULATION is derived at ingest: dark hours AND a
# female rider on the trip (join emp_legs.gender), or a WOMAN_TRAVELLING_ALONE
# alert -- the two conditions MoveInSync itself raises alerts for. Do that in
# ONE place, in ingest, not here. Absent the column, coverage goes to 0.0, the
# rule caps at WATCH, and the metric degrades instead of lying. Already tested.

# Deviation 7: sentiment comes from a deterministic Python lexicon over the
# TRANSLATED comment. The model does language; this arithmetic is tested Python.
_EXPERIENCE_SQL = """
SELECT avg(least(5.0, greatest(1.0, f.rating + 0.5 * f.sentiment)))
FROM feedback_normalised f JOIN trips t ON t.trip_id = f.trip_id
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
  {{SLICE}}
"""

METRICS: tuple[Metric, ...] = (
    # ota is first deliberately: the statement's own worked example is "OTA is
    # 78%", so it lands with a judge instantly.
    Metric("ota", "On-time arrival", "%", Direction.HIGHER, _OTA_SQL,
           (ReferenceKind.TREND, ReferenceKind.TARGET), "trips",
           ("actual_at", "scheduled_at"), target=90.0),
    # OTA is On-Time ARRIVAL and applies to LOGIN trips; OTD is On-Time
    # DEPARTURE and applies to LOGOUT trips. They are two named metrics in
    # MoveInSync's own vocabulary, not one metric sliced by direction — a console
    # reading "on-time arrival, logout" is not a thing. Both reuse _OTA_SQL with
    # a direction filter appended.
    Metric("otd", "On-time departure", "%", Direction.HIGHER,
           _OTA_SQL.replace("{{SLICE}}", "AND t.direction = 'logout' {{SLICE}}"),
           (ReferenceKind.TREND, ReferenceKind.TARGET), "trips",
           ("actual_at", "scheduled_at"), target=90.0),
    Metric("sla_breach", "SLA breach rate", "%", Direction.LOWER, _SLA_SQL,
           (ReferenceKind.TARGET,), "trips",
           ("actual_at", "scheduled_at"), target=10.0),
    Metric("vendor_ota", "Vendor on-time share", "%", Direction.HIGHER, _OTA_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "trips",
           ("actual_at", "scheduled_at", "vendor_id")),
    Metric("cost_per_trip", "Cost per trip", "INR", Direction.LOWER, _COST_SQL,
           (ReferenceKind.TREND, ReferenceKind.PEER), "costs", ("total_inr",)),
    # Deviation 2: a hard target — 100% is a compliance floor, not an aspiration.
    # This is the one metric where a hard target is genuinely right: a female or
    # special-needs employee cannot board before a marshal signs in, so 99% is
    # not "nearly compliant", it is a safety failure.
    Metric("marshal_compliance", "Marshal compliance (dark hours)", "%",
           Direction.HIGHER, _MARSHAL_SQL,
           (ReferenceKind.TARGET,), "trips", ("marshal_signed_in", "marshal_required"),
           target=100.0, hard_target=True),
    Metric("experience", "Employee experience", "score", Direction.HIGHER, _EXPERIENCE_SQL,
           (ReferenceKind.TREND,), "feedback", ("rating",)),
)

TIER_1_METRICS = ("ota", "otd", "sla_breach", "vendor_ota")


def by_id(metric_id: str) -> Metric:
    for m in METRICS:
        if m.id == metric_id:
            return m
    valid = ", ".join(m.id for m in METRICS)
    raise ValueError(f"unknown metric id {metric_id!r}; valid ids are {valid}")


def active(ids=TIER_1_METRICS) -> tuple[Metric, ...]:
    return tuple(m for m in METRICS if m.id in ids)


def _with_slice(sql: str, slc: Slice) -> str:
    predicate = "" if slc.dim is Dimension.NONE else f"AND {slc.dim.column} = ?"
    return sql.replace("{{SLICE}}", predicate)


def _params(slc: Slice, window: Window) -> list:
    p = [window.start_ms, window.end_ms]
    if slc.dim is not Dimension.NONE:
        p.append(slc.value)      # ALWAYS bound, never interpolated
    return p


def evaluate(con, metric: Metric, slc: Slice, window: Window) -> float | None:
    """None when the slice has no rows: a data gap, never a zero.

    A missing slice scoring 0% and breaching on a vendor that simply did not
    operate that week is the most damaging bug available in this layer.
    """
    row = con.execute(_with_slice(metric.sql, slc), _params(slc, window)).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def coverage(con, metric: Metric, slc: Slice, window: Window) -> float:
    """Fraction of rows where every column the metric needs is non-null.

    BUG F3: when the metric's SOURCE table lacks the SLICE column (feedback has
    no vendor_id), measure UNSLICED rather than returning 0.0 — otherwise a
    modelling gap becomes a wall of LOW_CONFIDENCE noise. Absence of the metric's
    OWN required column still returns 0.0, which is what deviation 6 needs.
    """
    if not metric.required_columns:
        return 1.0
    table = metric.source
    present = {r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()}
    if not set(metric.required_columns) <= present:
        return 0.0
    non_null = " AND ".join(f"{c} IS NOT NULL" for c in metric.required_columns)

    slice_col = None if slc.dim is Dimension.NONE else slc.dim.column.split(".", 1)[-1]
    sliceable = slice_col is not None and slice_col in present
    predicate = f" AND {slice_col} = ?" if sliceable else ""
    params = [slc.value] if sliceable else []

    row = con.execute(
        f"SELECT avg(CASE WHEN {non_null} THEN 1.0 ELSE 0.0 END) FROM {table} WHERE TRUE{predicate}",
        params).fetchone()
    return 0.0 if row is None or row[0] is None else float(row[0])


def distinct_values(con, dim: Dimension, window: Window) -> list[str]:
    col = dim.column
    rows = con.execute(
        f"SELECT DISTINCT {col} AS v FROM trips t "
        f"WHERE t.scheduled_at >= ? AND t.scheduled_at < ? AND {col} IS NOT NULL ORDER BY v",
        [window.start_ms, window.end_ms]).fetchall()
    return [r[0] for r in rows]


def evidence_sql(metric: Metric, slc: Slice, window: Window) -> str:
    """The literal-substituted form, so a human can paste it into the DuckDB CLI
    and get the same number. This is what the console shows on expand: "where did
    this number come from" answered with a query, not a claim."""
    sql = _with_slice(metric.sql, slc)
    sql = sql.replace("?", str(window.start_ms), 1).replace("?", str(window.end_ms), 1)
    if slc.dim is not Dimension.NONE:
        sql = sql.replace("?", "'" + slc.value.replace("'", "''") + "'", 1)
    return sql.strip()
```

- [ ] **Step 2: Write the tests**

Assert, at minimum:

```python
def test_all_seven_metrics_are_defined_with_ota_first()
def test_every_metric_declares_at_least_one_reference_point()
    # The mandatory bar is contextualisation against at least one reference
    # point. Satisfied by construction, not by a feature.
def test_only_night_compliance_has_a_hard_target()
def test_an_unknown_metric_id_is_refused_with_the_valid_ids_named()
def test_every_metric_returns_exactly_one_number_for_the_unsliced_window()   # skips experience
def test_every_metric_returns_one_number_for_every_valid_slice_dimension()
def test_an_empty_slice_yields_none_rather_than_zero()
def test_coverage_ignores_a_slice_column_the_source_table_does_not_have()    # BUG F3
def test_evidence_sql_has_no_placeholders_left_and_runs_standalone()
def test_the_night_predicate_matches_more_than_zero_rows()                   # BUG F1
def test_the_degrading_vendor_is_visibly_worse_than_a_peer()
```

Two of these are not optional. **`test_an_empty_slice_yields_none_rather_than_zero`** guards the worst bug in this layer. **`test_the_night_predicate_matches_more_than_zero_rows`** is bug F1's tripwire — assert `count(*) > 0` for the night population directly, because a metric that silently measures nothing returns `None` and looks like a data gap.

`test_evidence_sql_has_no_placeholders_left_and_runs_standalone` should `con.sql(evidence_sql(...))` and compare the result to `evaluate(...)`. If they disagree, the console is showing a query that does not produce the number next to it.

- [ ] **Step 3: Run, and print the real numbers**

Run: `cd service && .venv/bin/python -m pytest tests/test_registry.py -q -s`

Print and record the unsliced value of every metric, plus `vendor_ota` for the worst and median vendor. **Task 5 calibrates the thresholds against these**, so they are not optional output.

- [ ] **Step 4: Break-it-to-prove-it**

Remove the `row[0] is None` check in `evaluate`, rerun → the empty-slice test FAILS. Restore.
Delete the `{{SLICE}}` replacement so slices are ignored, rerun → the degrading-vendor test FAILS (both vendors return the same unsliced number). Restore.
Change the night predicate's `< 6` to `< 0`, rerun → the night-population test FAILS. Restore. That is F1.

- [ ] **Step 5: Commit** — `feat(registry): six governed metric definitions, slices bound not interpolated`

---

### Task 4: References and the verdict engine (~50 min, critical path)

**Files:** `service/signaldesk/references.py`, `service/signaldesk/verdict.py`, `service/tests/test_references.py`, `service/tests/test_verdict.py`

**Interfaces produced:** `resolve(con, metric, slice, window) -> tuple[Reference, ...]`, `MIN_PEERS`, `delta()`, `tier_for()`, `cap_for_confidence()`, `cause_for()`, `evaluate_finding()`, `rank()`, `audiences_for()`.

- [ ] **Step 1: `references.py`**

```python
"""What a metric is judged against. A metric without one is just a number."""
from __future__ import annotations

from . import registry
from .schemas import Dimension, Metric, Reference, ReferenceKind, Slice, Window

MIN_PEERS = 3          # a median over two values is not a peer comparison
TREND_WINDOWS = 4


def resolve(con, metric: Metric, slc: Slice, window: Window) -> tuple[Reference, ...]:
    """Every declared reference that can actually be computed, in declaration
    order. One that cannot is OMITTED, never faked."""
    out: list[Reference] = []
    for kind in metric.refs:
        if kind is ReferenceKind.TREND:
            r = _trend(con, metric, slc, window)
        elif kind is ReferenceKind.TARGET:
            r = Reference(ReferenceKind.TARGET, metric.target, "SLA target")
        else:
            r = _peer(con, metric, slc, window)
        if r is not None:
            out.append(r)
    return tuple(out)


def _trend(con, metric, slc, window) -> Reference | None:
    """Mean of the metric over the four COMPLETE PRECEDING windows, excluding the
    one under evaluation. Averaging only the windows that returned a value means
    one missing week degrades the reference rather than voiding it."""
    values = [v for v in (registry.evaluate(con, metric, slc, window.shifted_back(b))
                          for b in range(1, TREND_WINDOWS + 1)) if v is not None]
    if not values:
        return None
    return Reference(ReferenceKind.TREND, sum(values) / len(values), "4-week average")


def _peer(con, metric, slc, window) -> Reference | None:
    if slc.dim is Dimension.NONE:
        return None
    peers = [v for other in registry.distinct_values(con, slc.dim, window)
             if other != slc.value                      # the subject is not its own peer
             for v in [registry.evaluate(con, metric, Slice(slc.dim, other), window)]
             if v is not None]
    if len(peers) < MIN_PEERS:
        return None
    peers.sort()
    mid = len(peers) // 2
    median = peers[mid] if len(peers) % 2 else (peers[mid - 1] + peers[mid]) / 2
    return Reference(ReferenceKind.PEER, median, "peer median")
```

- [ ] **Step 2: `verdict.py`**

```python
"""Pure functions of their inputs. No I/O, no clock, no model.

This module is why the product is trustworthy: the reasoning is unit-testable,
and nothing here can produce a number the model influenced.
"""
from __future__ import annotations

from . import constants as C, references, registry
from .schemas import (Audience, Cause, Dimension, Direction, Finding, Metric,
                      Reference, ReferenceKind, Slice, Tier, Window, finding_id)


def delta(observed: float, reference: float, better: Direction) -> float:
    """The shortfall as a fraction of the reference, signed so POSITIVE ALWAYS
    MEANS WORSE whichever way the metric points.

    Defining it this way removes the sign confusion a lower-is-better metric like
    sla_breach otherwise invites: one formula covers both directions, and gap is
    delta x reference, so its sign agrees with the tier by CONSTRUCTION rather
    than by care.
    """
    if reference == 0.0:
        if observed == 0.0:
            return 0.0
        return 1.0 if better is Direction.LOWER else -1.0
    shortfall = (reference - observed) if better is Direction.HIGHER else (observed - reference)
    return shortfall / abs(reference)


def tier_for(d: float, hard_target: bool) -> Tier:
    # Deviation 2: a hard target admits no tolerance. Read literally, the spec's
    # "a TARGET missed outright -> BREACH" would make WATCH and CONCERN
    # unreachable for EVERY target metric.
    if hard_target:
        return Tier.BREACH if d > 0.0 else Tier.PASS
    if d <= C.PASS_MAX:
        return Tier.PASS
    if d <= C.WATCH_MAX:
        return Tier.WATCH
    if d <= C.CONCERN_MAX:
        return Tier.CONCERN
    return Tier.BREACH


def cause_for(kind: ReferenceKind) -> Cause:
    return {ReferenceKind.TARGET: Cause.BELOW_TARGET,
            ReferenceKind.TREND: Cause.TREND_REGRESSION,
            ReferenceKind.PEER: Cause.PEER_LAGGARD}[kind]


def cap_for_confidence(tier: Tier, confidence: float) -> Tier:
    """Low confidence caps severity; it never improves it."""
    if confidence >= C.MIN_TRUSTED_CONFIDENCE:
        return tier
    return Tier.WATCH if tier > Tier.WATCH else tier


def audiences_for(metric_id: str, slc: Slice, tier: Tier) -> frozenset[Audience]:
    """Assigned by rule, not by the model. A set, not one value: a BREACH assigns
    two and a single field would silently drop a recipient."""
    out = set()
    if tier is Tier.BREACH:
        out |= {Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER}
    if metric_id in ("vendor_ota", "cost_per_trip"):
        out.add(Audience.FACILITIES_HEAD)
    else:
        out.add(Audience.TRANSPORT_MANAGER)
    if slc.dim is Dimension.SHIFT:
        out.add(Audience.LINE_MANAGER)
    return frozenset(out)


def evaluate_finding(con, metric: Metric, slc: Slice, window: Window,
                     feed_confidence: float) -> Finding | None:
    observed = registry.evaluate(con, metric, slc, window)
    confidence = feed_confidence * registry.coverage(con, metric, slc, window)

    if observed is None:
        # An unmeasurable OVERALL metric is a finding — the agent is loud about
        # what it cannot read. An unmeasurable SLICE is not: a vendor that did not
        # operate this week is not news.
        if slc.dim is not Dimension.NONE:
            return None
        return Finding(finding_id(metric.id, slc, window), metric.id, slc, window,
                       0.0, (), Tier.WATCH, Cause.DATA_GAP, 0.0, confidence,
                       audiences_for(metric.id, slc, Tier.WATCH),
                       registry.evidence_sql(metric, slc, window))

    refs = references.resolve(con, metric, slc, window)
    if not refs:
        # An uncontextualised number is exactly what this product refuses to ship.
        return None

    # Deviation 3: keep every reference, take the WORST tier. cause and gap come
    # from the reference that produced it; ties keep the earlier-declared one.
    worst, firing, worst_delta = Tier.PASS, refs[0], float("-inf")
    for ref in refs:
        d = delta(observed, ref.value, metric.better)
        hard = metric.hard_target and ref.kind is ReferenceKind.TARGET
        t = tier_for(d, hard)
        if t > worst or (t is worst and d > worst_delta):
            worst, firing, worst_delta = t, ref, d

    capped = cap_for_confidence(worst, confidence)
    if capped is not worst:
        cause = Cause.LOW_CONFIDENCE
    elif capped is Tier.PASS:
        cause = Cause.ON_REFERENCE
    else:
        cause = cause_for(firing.kind)

    return Finding(finding_id(metric.id, slc, window), metric.id, slc, window,
                   observed, refs, capped, cause, worst_delta * firing.value,
                   confidence, audiences_for(metric.id, slc, capped),
                   registry.evidence_sql(metric, slc, window))


def rank(findings: list[Finding]) -> list[Finding]:
    """(tier desc, |gap| desc, confidence desc, id) — a TOTAL order.

    No arithmetic combines the keys, so no number of WATCHes can add up to a
    BREACH. The trailing id is not decoration: without a total order the sweep
    determinism test fails intermittently on ties, which is the worst kind of
    failure to debug at 15:00.
    """
    return sorted(findings, key=lambda f: (-f.tier.value, -abs(f.gap), -f.confidence, f.id))
```

- [ ] **Step 3: Tests that must exist**

```python
# references
def test_trend_is_the_mean_of_the_four_preceding_windows_and_excludes_the_evaluated_one()
def test_trend_averages_only_the_windows_that_returned_a_value()
def test_trend_is_omitted_when_no_preceding_window_has_data()
def test_peer_is_the_median_across_the_other_values_of_the_same_dimension()
def test_peer_is_omitted_rather_than_computed_on_two_peers()
def test_peer_is_omitted_for_an_unsliced_finding()
def test_references_come_back_in_declaration_order_so_tie_breaking_is_stable()

# verdict
def test_one_formula_covers_both_directions()                       # 4 data points
def test_all_four_tiers_are_reachable_and_boundaries_are_inclusive_upward()  # parametrised
def test_a_hard_target_breaches_on_any_shortfall_at_all()
def test_a_zero_reference_saturates_rather_than_dividing_by_zero()
def test_gap_sign_agrees_with_tier_for_both_directions()            # 4 data points
def test_takes_the_worst_tier_across_every_reference_and_keeps_them_all()
def test_a_passing_metric_carries_no_accusatory_cause()
def test_low_confidence_caps_at_watch_and_says_why()
def test_low_confidence_does_not_promote_a_pass_to_a_watch()
def test_an_unmeasurable_overall_metric_is_a_finding_not_silence()
def test_an_empty_slice_is_skipped_rather_than_reported_as_a_gap()
def test_a_metric_with_no_computable_reference_emits_nothing()
def test_one_breach_outranks_twenty_watches()                       # the no-summing property
def test_a_breach_sliced_by_shift_reaches_all_three_audiences()
```

`test_one_breach_outranks_twenty_watches` must use **twenty** WATCHes with large gaps against one BREACH with a tiny gap. That is the property a weighted score would violate, and one WATCH proves nothing.

`test_gap_sign_agrees_with_tier_for_both_directions` needs four data points: HIGHER-worse, LOWER-worse, HIGHER-better, LOWER-better. A sign-flipped gap produces a confidently wrong sentence.

- [ ] **Step 4: Break-it-to-prove-it**

`t > worst` → `t < worst` → the worst-tier test FAILS. Restore.
Delete the `cap_for_confidence` call → both confidence tests FAIL. Restore.
Move `-abs(f.gap)` ahead of `-f.tier.value` in `rank` → the twenty-watches test FAILS. Restore. That is the no-summing property demonstrated rather than asserted.
`MIN_PEERS = 2` → the two-peers test FAILS. Restore.
`range(1, ...)` → `range(0, ...)` in `_trend` → the exclusion test FAILS. Restore.

- [ ] **Step 5: Commit** — `feat(verdict): four-tier rules, signed gap, ordinal ranking, rule-assigned audiences`

---

### Task 5: The sweep, the replay clock, and the API (~40 min, critical path)

**Files:** `service/signaldesk/sweep.py`, `service/signaldesk/api.py`, `service/tests/test_sweep.py`

**Interfaces produced:** `Clock`, `ReplayClock`, `sweep(con, clock, health, metric_ids) -> SweepRun`, `STORE`, and the HTTP surface.

**This is where the replay clock lands** — capability 1 of Amendment 1.1, and the single highest-value demo addition available. §7.1 already required an injected clock so runs are reproducible; replay extends it to advance the simulated date at 60× so findings fire live on stage.

- [ ] **Step 1: `sweep.py`**

```python
"""The SENSE step. Iterates every (metric x slice) pair, evaluates the rules, and
stores findings. NO PROMPT IS INVOLVED.

This is the step that satisfies "agentic — senses, reasons and acts", and it must
be visibly automatic in the demo: the manual trigger exists so a judge can watch
it fire, not because the loop needs asking.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from . import registry, verdict
from .schemas import Dimension, FeedHealth, Finding, Slice, Window


@dataclass
class Clock:
    """A fixed simulated clock. The demo drives this, not wall-clock time, so the
    same dataset always produces the same findings."""
    now_ms: int

    def millis(self) -> int:
        return self.now_ms


@dataclass
class ReplayClock(Clock):
    """Advances the simulated date at `speed` x real time, so a 90-day dataset
    replays in minutes and alerts fire LIVE on stage.

    This is what turns "the loop starts without a prompt" from a claim a judge
    has to take on trust into something they watch happen.
    """
    speed: float = 60.0 * 60.0 * 24.0     # one simulated day per real second
    started_at: float = field(default_factory=time.monotonic)
    running: bool = False

    def millis(self) -> int:
        if not self.running:
            return self.now_ms
        elapsed = time.monotonic() - self.started_at
        return int(self.now_ms + elapsed * self.speed * 1000)

    def start(self):
        self.started_at = time.monotonic()
        self.running = True

    def stop(self):
        self.now_ms = self.millis()
        self.running = False


@dataclass(frozen=True)
class SweepRun:
    run_id: str
    window: Window
    findings: tuple[Finding, ...]
    feed_health: dict[str, FeedHealth]
    swept_at_ms: int


def sweep(con, clock: Clock, health: dict[str, FeedHealth],
          metric_ids=registry.TIER_1_METRICS, window_days: int = 7) -> SweepRun:
    now = clock.millis()
    window = Window(now - window_days * 86_400_000, now)

    found: list[Finding] = []
    for metric in registry.active(metric_ids):
        feed_conf = health[metric.source].confidence if metric.source in health else 0.0
        f = verdict.evaluate_finding(con, metric, Slice.all(), window, feed_conf)
        if f:
            found.append(f)
        for dim in Dimension:
            if dim is Dimension.NONE:
                continue
            for value in registry.distinct_values(con, dim, window):
                f = verdict.evaluate_finding(con, metric, Slice(dim, value), window, feed_conf)
                if f:
                    found.append(f)

    ranked = verdict.rank(found)
    # Derived from the simulated clock and the finding count, not a uuid, so a
    # rerun of the demo produces the same id and a bookmarked URL still resolves.
    run_id = f"run-{now}-{len(ranked):x}"
    return SweepRun(run_id, window, tuple(ranked), health, now)


class Store:
    """In-process only. Audit-log persistence is explicitly out of scope; this
    exists so the console and the interrogator can re-read a run."""

    def __init__(self):
        self._runs: dict[str, SweepRun] = {}
        self._findings: dict[str, Finding] = {}
        self._latest: str | None = None
        self._lock = threading.Lock()

    def put(self, run: SweepRun):
        with self._lock:
            self._runs[run.run_id] = run
            self._findings.update({f.id: f for f in run.findings})
            self._latest = run.run_id

    def get(self, run_id: str) -> SweepRun | None:
        return self._runs.get(self._latest if run_id == "latest" else run_id)

    def finding(self, finding_id: str) -> Finding | None:
        return self._findings.get(finding_id)


STORE = Store()
```

- [ ] **Step 2: `api.py` — the HTTP contract the console is written against**

```
POST /api/sweep                     trigger a sweep, returns {runId, findingCount}
GET  /api/runs/{run_id}/findings    ranked findings ("latest" is an alias)
GET  /api/findings/{id}             one finding with its evidence
GET  /api/health/feeds              FeedHealth per feed
GET  /api/health                    liveness: {status, activeMetrics, clock}
GET  /api/runs/{run_id}/brief       the composed brief for an audience
POST /api/dispatch/{run_id}         send it
POST /api/replay/start|stop         the replay clock            [Tier 2]
GET  /api/cost                      token + rupee accounting     [Tier 2]
POST /api/ask                       {runId, question} -> answer + tool trace  [Tier 2]
```

Startup order is explicit and in one function — **bug F6**: load the feeds, then compute health, then sweep once so the console opens on a completed sweep rather than an empty shell. Do not make any of that an import side effect.

CORS: allow the console origin from an env var (`SIGNALDESK_CORS_ORIGINS`, comma-separated, default `http://localhost:5173`). A wildcard is fine on a laptop and wrong on a public URL, and it cannot be pointed at the deployed console without a redeploy.

- [ ] **Step 3: Tests**

```python
def test_produces_findings_without_any_prompt_or_question()
def test_the_same_dataset_and_clock_produce_identical_findings()   # ids, observed, tiers
def test_findings_come_back_ranked()
def test_every_metric_slice_combination_is_visited()
def test_the_replay_clock_advances_the_simulated_date_while_running()
def test_the_replay_clock_is_frozen_when_stopped()
def test_a_stopped_replay_clock_keeps_the_time_it_reached()
def test_the_tier_distribution_is_printed_for_calibration()
def test_the_degrading_vendor_appears_as_a_concern_or_worse()
```

The two replay tests need two data points each and must not sleep for long — set `speed` high, `start()`, assert `millis()` advanced, `stop()`, assert it stopped.

- [ ] **Step 4: CALIBRATE — measure the thresholds, then pin them**

Spec §6.3 requires this and names the failure it prevents: *a threshold nobody measured either fires on everything or nothing.* The bands in `constants.py` are provisional until this step.

Run the sweep against the real dataset and print the tier distribution. Judge it against three criteria:

1. **A mix across all four tiers** — every tier with at least one finding. `PASS` at 95% means the agent has nothing to say; `BREACH` at 40% means nothing stands out.
2. **The worst vendor at `CONCERN` or `BREACH`.** This is the demo.
3. **At least one `BREACH`, and no more than about five.** A brief with twenty breaches is a wall, not a decision.

Adjust `PASS_MAX` / `WATCH_MAX` / `CONCERN_MAX` in whole percentage points, one at a time. **Record the measured distribution in a comment above the constants — with the real numbers filled in, not placeholders.** Then pin a golden assertion at ~80% of what was measured.

- [ ] **Step 5: Break-it-to-prove-it**

Replace the injected clock with `time.time()`, rerun → the determinism test FAILS. Restore. That is why the simulated clock is a design decision rather than a testing convenience.

- [ ] **Step 6: Commit** — `feat(sweep): unprompted sweep on a simulated clock, replay at 60x, ranked store`

---
### Task 6: Compose, validate, deliver — and count the cost (~55 min, parallel from 10:05)

**Files:** `service/signaldesk/model.py`, `compose.py`, `delivery.py`, `service/tests/test_compose.py`, `test_delivery.py`

**Interfaces produced:** `SarvamClient.complete()`, `COST` (a token/rupee accumulator), `template_brief()`, `sarvam_brief()`, `validate_narrative()`, `Channel`, `slack_send()`, `ses_send()`, `dispatch()`, `DISPATCH_LOG`.

**Build this against hardcoded fake `Finding` objects from minute one.** Do not wait for Task 4. The contracts from Task 1 are what make that possible.

- [ ] **Step 1: `model.py` — the client and the cost meter**

Capability 2 of Amendment 1.1 lands here. Criterion 2 ("agentic design & cost at scale") is 20 points and asks for this by name; the previous plan only argued it in prose.

```python
"""The model layer's whole surface. It produces language; it never produces a
figure and never sees a raw row."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from openai import OpenAI

from . import constants as C

BASE_URL = "https://api.sarvam.ai/v1"
MODEL = "sarvam-105b"      # Sarvam-M is deprecated and no longer served


class TruncatedResponse(RuntimeError):
    """The model hit its token ceiling or returned nothing.

    Raised rather than returned so every caller must decide. SarvamComposer
    catches it and sends the template brief; the interrogator catches it and
    withholds. Silently returning a half-written brief is the one outcome
    neither of them should have to guess at.
    """


@dataclass
class CostMeter:
    """Tokens and rupees per interaction, extrapolated to scale.

    The architecture is what makes this number good: ONE model call per brief
    rather than one per row, so tokens stay flat as row counts grow. That is the
    cost-at-scale story, and it is now a figure on screen rather than a claim.
    """
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_purpose: dict[str, int] = field(default_factory=dict)

    def record(self, purpose: str, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.output_tokens += getattr(usage, "completion_tokens", 0) or 0
        self.by_purpose[purpose] = self.by_purpose.get(purpose, 0) + 1

    @property
    def inr(self) -> float:
        return (self.input_tokens / 1000 * C.INR_PER_1K_INPUT_TOKENS
                + self.output_tokens / 1000 * C.INR_PER_1K_OUTPUT_TOKENS)

    @property
    def inr_per_org_per_month(self) -> float:
        """The figure that makes the argument: cost per ORGANISATION, not per
        employee, because the model sees aggregates rather than rows.

        Measured against the real rate, one brief is ~1,900 tokens ~ Rs 0.09;
        three audiences daily is ~Rs 8/month -- and that total is FLAT whether
        the client has 500 employees or 50,000. Per-employee cost therefore
        falls as the client grows, which is the opposite of how a per-row
        pipeline behaves.
        """
        if not self.calls:
            return 0.0
        return self.inr / self.calls * 3 * 30

    def snapshot(self) -> dict:
        per_call = (self.input_tokens + self.output_tokens) / self.calls if self.calls else 0
        org_month = self.inr_per_org_per_month
        return {
            "calls": self.calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "tokensPerCall": round(per_call),
            "inr": round(self.inr, 4),
            "inrPerOrgPerMonth": round(org_month, 2),
            "employeesAtScale": C.EMPLOYEES_AT_SCALE,
            # The number that carries the argument: per-employee cost FALLS as
            # the client grows, because one brief covers the whole org.
            "inrPerEmployeePerMonth": round(org_month / C.EMPLOYEES_AT_SCALE, 6),
            "byPurpose": dict(self.by_purpose),
            "pricingConfigured": C.INR_PER_1K_INPUT_TOKENS > 0,
            # Rs 0.03/629 tokens is a rounded dashboard figure: +/-17%. Show
            # "fractions of a rupee", never three significant figures.
            "rateIsApproximate": True,
        }


COST = CostMeter()


class SarvamClient:
    """Sarvam's API is OpenAI-compatible, so the official SDK is used with a
    base_url override.

    No retry, no backoff, no circuit breaker: explicitly out of scope. A failed
    call degrades to the template brief, which is a better answer than a slow one.
    """

    def __init__(self, api_key: str | None = None):
        self._client = OpenAI(api_key=api_key or os.environ.get("SARVAM_API_KEY", ""),
                              base_url=BASE_URL)

    # MEASURED 2026-09-04: sarvam-105b bills reasoning tokens as
    # completion_tokens without surfacing them in message.content. Replying with
    # the single word "READY" cost 195 completion tokens; one tool call cost
    # 199; a ten-word translation cost 19. So the overhead is real, variable,
    # and up to ~200 tokens BEFORE any prose. A 700-token ceiling on a
    # 200-word brief is uncomfortably close to truncating.
    DEFAULT_MAX_TOKENS = 1600

    def complete(self, messages: list[dict], purpose: str = "brief",
                 max_tokens: int | None = None) -> str:
        r = self._client.chat.completions.create(
            model=MODEL, messages=messages,
            max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS)
        if r.usage:
            COST.record(purpose, r.usage)
        choice = r.choices[0]
        text = (choice.message.content or "").strip()

        # A truncated brief is the DANGEROUS failure, not an obvious one: half a
        # sentence whose every figure is correct passes the numeric validator
        # and goes on stage mid-word. Treat it as a hard failure so the caller
        # falls back to the deterministic template.
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{purpose} hit the {max_tokens or self.DEFAULT_MAX_TOKENS}-token "
                f"ceiling; reasoning overhead is billed but not returned")
        if not text:
            raise TruncatedResponse(f"{purpose} returned empty content "
                                    f"(finish_reason={choice.finish_reason})")
        return text
```

**The rate is measured, not invented.** 629 tokens billed at ₹0.03 on 2026-09-04 gives ~₹0.048 per 1k blended. Two things follow:

- **Say "fractions of a rupee", not three significant figures.** ₹0.03 is a rounded dashboard display, so the rate is really ₹0.040–0.056 per 1k — ±17%. `rateIsApproximate` is in the payload so the console can hedge honestly. A precise-looking made-up number is the one thing a judge can check and catch.
- **Cost is not a constraint on this build.** The rate is ~₹0.048 per 1k tokens; a brief is ₹0.09 and an interrogation question ₹0.38. The team's allocation is topped up per request, so nothing here needs rationing. Report the *rate* honestly on stage and let the per-organisation figure below carry the argument — do not present a credit balance as if it were a limit we engineered around.

**The number that carries the argument is per-organisation, not per-interaction.** One brief is ~2,200 tokens ≈ ₹0.10 (revised upward after measuring the reasoning overhead); three audiences daily is **~₹9.50 per month for the entire client** — and that total is *flat* whether they have 500 employees or 50,000, because the model sees aggregates rather than rows. So per-employee cost **falls** as the client grows: ₹0.016/employee/month at 500, ₹0.0002 at 50,000. A per-row pipeline behaves the opposite way, and that contrast is the whole of criterion 2.

- [ ] **Step 2: `compose.py` — the validator is the load-bearing part**

```python
import re

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DECIMAL = re.compile(r"-?\d+\.\d+")


def validate_narrative(narrative: str, run) -> str | None:
    """Returns the offending figure, or None if every number checks out.

    Every number in the narrative must match a figure in the findings to two
    decimal places. Only DECIMALS are treated as metric claims — bare integers
    are counts and years, and ISO dates are stripped first.

    If validation fails the brief is sent from the deterministic template
    instead. A wrong number in a leadership brief is worse than plain prose.
    """
    allowed = set()
    for f in run.findings:
        for v in (f.observed, f.gap, abs(f.gap), f.confidence, f.confidence * 100):
            allowed.add(f"{v:.2f}")
        for ref in f.refs:
            allowed.add(f"{ref.value:.2f}")
    for h in run.feed_health.values():
        allowed.add(f"{h.confidence:.2f}")
        allowed.add(f"{h.confidence * 100:.2f}")

    for raw in _DECIMAL.findall(_ISO_DATE.sub("", narrative)):
        if f"{float(raw):.2f}" not in allowed:
            return raw
    return None
```

Rounding both sides to two places is what makes `61.4` and `61.40` the same figure while keeping `61.42` a different one.

`template_brief(run, audience)` is deterministic prose over the ranked findings for that audience: tier, metric label, slice, observed value, **every** reference by name, the cause in plain English, and the confidence **only when below 0.9**. `sarvam_brief()` calls the model once with the findings serialised compactly — **never raw rows** — then validates, and falls back to the template on either a validation failure or an exception.

The system prompt must instruct: write for the named audience, cite the reference point for every claim, mention confidence where below 0.9, **introduce no figure not present in the findings**, and end with one sentence naming the action to take.

- [ ] **Step 3: Tests that must exist**

```python
# compose
def test_the_template_cites_the_reference_point_for_every_claim()
def test_the_template_mentions_confidence_only_when_below_nine_tenths()   # 2 data points
def test_the_template_introduces_no_figure_absent_from_the_findings()
def test_it_produces_an_honest_brief_when_nothing_is_wrong()
def test_the_validator_accepts_a_narrative_whose_every_figure_is_in_the_findings()
def test_the_validator_rejects_an_invented_figure()
def test_the_validator_rejects_a_figure_that_is_close_but_not_equal_to_two_places()  # 61.42
def test_the_validator_ignores_dates_and_integers_that_are_not_metric_claims()
def test_the_validator_tolerates_trailing_zero_differences()             # 61.4 == 61.40
def test_sarvam_brief_substitutes_the_template_when_the_model_invents_a_figure()
def test_sarvam_brief_substitutes_the_template_when_the_model_is_unreachable()
def test_the_prompt_carries_findings_not_rows_and_no_sql()
def test_one_model_call_per_brief()                                      # the cost story

# delivery
def test_breach_and_concern_go_to_both_channels()
def test_watch_goes_to_slack_only()
def test_pass_goes_nowhere()
def test_a_channel_failure_is_recorded_and_does_not_lose_the_finding()
def test_every_dispatch_records_what_was_sent_to_whom_and_from_which_findings()
def test_the_webhook_url_never_appears_in_a_log_line_or_a_result()
```

`test_the_prompt_carries_findings_not_rows_and_no_sql` must assert the prompt contains no `trip_id` and no `SELECT`. `evidence_sql` lives on the finding, and leaking it into the prompt hands the model raw SQL to imitate.

`test_the_webhook_url_never_appears_in_a_log_line_or_a_result` is not paranoia — a Slack webhook URL is a credential, and the dispatch result is rendered in the console.

- [ ] **Step 4: Send one real message, and read it**

With `SLACK_WEBHOOK_URL` and `SARVAM_API_KEY` set, sweep and dispatch. **Read the Slack message as a transport manager would.** It must name a specific vendor, quote a reference point, and be forwardable without editing.

If it reads like a data dump, fix the template now. This wording is what the demo is judged on, and it is far cheaper to fix here than after the model is layered on top.

Check the log for a rejected narrative. **If validation fires, tighten the prompt — do not loosen the validator.** The usual cause is the model recomputing a percentage change; add one line naming that specific mistake.

- [ ] **Step 4b: Handle truncation as a fallback, and test it**

`sarvam_brief()` already falls back to the template on an exception, so
`TruncatedResponse` is handled by construction — but assert it, because this is
the failure mode most likely to reach a stage:

```python
def test_sarvam_brief_substitutes_the_template_when_the_model_truncates():
    # A half-written brief whose figures are all correct PASSES the numeric
    # validator. Truncation has to be caught before validation, not by it.
    model = StubModel()
    model.raises = TruncatedResponse("brief hit the ceiling")
    brief = sarvam_brief(run(), Audience.FACILITIES_HEAD, model=model)
    assert "[BREACH]" in brief          # the template's marker
```

And one that pins the reason the ceiling is generous:

```python
def test_the_default_token_ceiling_leaves_room_for_reasoning_overhead():
    # Measured: ~200 completion tokens of reasoning before any prose.
    # A 200-word brief is ~280 tokens of prose. 1600 leaves real headroom.
    assert SarvamClient.DEFAULT_MAX_TOKENS >= 1200
```

- [ ] **Step 5: Break-it-to-prove-it**

Return the model narrative unconditionally → the invented-figure test FAILS. Restore.

Remove the `finish_reason == "length"` check → the truncation test FAILS. Restore.
That guard is the only thing standing between a truncated brief and a judge.
Make `_DECIMAL` match integers too → the dates-and-integers test FAILS. Restore.
Let the send exception propagate → the channel-failure test FAILS. Restore.

- [ ] **Step 6: Commit** — `feat(compose): validated Sarvam brief with template fallback, real Slack and SES delivery, cost meter`

---

### Task 7: The console — ranked findings, expandable to evidence (~60 min, parallel from 10:05)

**Files:** `console/src/api/{types,client}.ts`, `console/src/App.tsx`, `console/src/components/{TierBadge,FindingRow,EvidencePanel,FindingsList,FeedHealthStrip,BriefPreview,CostMeter}.tsx`, tests alongside.

**Build against hardcoded fake findings from minute one.** The console is on the critical path for the *demo*, not for the data.

Severity is encoded **in form as well as colour** — a stripe and the word, never colour alone. That is an accessibility requirement and it also survives a projector that washes out red.

`client.ts` reads its base from `import.meta.env.VITE_API_BASE ?? ''` and **trims a trailing slash** (`.replace(/\/+$/, '')`) — pasting a URL out of a console is how a doubled slash becomes a 404 that looks like a routing bug. In development the Vite proxy handles `/api`; in production there is no proxy.

Tier 1 console:

- [ ] **Findings list** — ranked, each row showing tier badge, metric label, slice, observed value, and every reference inline
- [ ] **Row expands** to observed value, every reference, the rule that fired, the confidence, the audiences, and `evidence_sql` in a `<pre>`
- [ ] **Confidence shown only below 0.9**, in the row
- [ ] **Feed health strip** — rows loaded, quarantined, unmatched, confidence per feed, with a flag when confidence is below 0.9. **A quarantined row is a finding, not a log line**, so the count is a number on screen.
- [ ] **Brief preview** with a dispatch button and per-channel results
- [ ] **Cost meter** — calls, tokens per call, ₹ per interaction, and the extrapolation, with the honest "pricing not configured" state when the rates are still zero
- [ ] **An empty-state that says so plainly** when a sweep found nothing

Tests (Vitest + Testing Library) must assert: rows render in server order; severity appears as text not only colour; every reference point is shown; confidence is disclosed only below 0.9; the evidence panel is hidden until asked and then shows the SQL; the empty state renders; the cost meter shows the unconfigured state without inventing a rupee figure.

- [ ] **Break-it-to-prove-it:** delete the `confidence < 0.9` guard → the disclosure test FAILS. Remove the tier word from `TierBadge`, leaving the stripe → the colour-alone test FAILS. Restore both.

- [ ] **Commit** — `feat(console): ranked findings expandable to references, rule and evidence SQL, plus feed health and cost`

---

## ⛔ 13:00 GATE — Tier 1 is done or it is not

Do not start Tier 2 until every line is true. If it is 13:30 and this is red, **keep working on Tier 1** — a complete narrow product beats four unfinished halves, and this gate is the whole reason the plan is tiered.

- [ ] `pytest -q` green; `cd console && npm test` green
- [ ] The service sweeps **once on startup with no prompt** — point at the log line
- [ ] `POST /api/sweep` returns a runId and a non-zero finding count **on the real dataset**
- [ ] `POST /api/dispatch/{runId}` puts a brief **in the real Slack channel**
- [ ] That brief names a specific vendor, cites a reference point, and discloses confidence where it is below 0.9
- [ ] The tier distribution covers **all four tiers**, and the measured figures are written into `constants.py` — with real numbers, not placeholders
- [ ] **The OTA/OTD target is data-derived or absent — not the spec's 90%.** `docs/real-dataset-mapping.md` §10b measured 59.1% on-time arrival against a 90% target, which makes *every* slice BREACH and the ranking meaningless — the first question a judge asks becomes "is your data broken?". Either drop `TARGET` from `ota`/`otd` and rank on TREND + PEER (option 1 there, preferred), or set `target=` to the measured P75 of `vendor_ota` and label it *data-derived* in the brief (option 2). Whichever: the constant carries the measured distribution in a comment, and the brief never prints "target 90%" unless this customer's contract says so. Task 5 Step 4 is where this happens; this line is here so it is *checked*, not assumed.
- [ ] **Every Tier 2 item has a name against it**, and the Task 9 write grant to Teammate B has been said in the channel (see "Work split")
- [ ] The console opens on a **completed sweep**, rows expand to `evidence_sql`, feed health shows a non-zero quarantined count
- [ ] No credential in `git log -p`:
      `git log -p | grep -iE 'hooks\.slack\.com/services/[A-Z0-9]{5,}|sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}' | grep -v REPLACE`

**Then say the demo out loud in two minutes:** "It swept without being asked. It found this. Here is the query it used. Here is what it couldn't read. It sent this to Slack." If that does not land, the problem is the brief's wording, not a missing feature — and no Tier 2 item fixes it.

**Then write the demo script.** Build only what the script needs from here.

---

# TIER 2 — pick in this order (13:00 → 16:00)

**Reordered three times.** Once by me against the statement; once after an
independent review scored the plan 77/100; and once more after an adversarial
judge's read against the PDF ([`docs/judge-review-2026-09-05.md`](../../judge-review-2026-09-05.md))
scored the *likely delivered* state 64/100 and showed that the reserve rule
guaranteed R1 and R3 would never be built. **The order below is the third
revision and it is the one to follow.** Three changes from the second:

- **8d is out of Tier 2** (→ R9). ~50 real minutes for ~2 points, and as scoped it
  aggregates by shift band when the PDF asks "*who* made it, *who* was late". M3
  is already met; `audiences_for` already routes `LINE_MANAGER`. Its minutes buy
  **R1 + R3**, which answer two things the PDF names — sustainability (§3 *and*
  §4) and multi-tenancy (bonus) — for fewer minutes and more points.
- **8c drops behind Task 11.** 8c is the nicer story (sixth solution form, when
  two are required); Task 11 is the one whose *absence a judge asks about* —
  "where is cost? where is safety?" — because at 13:00 the product is
  timeliness-only and the T&F head's "coherent cost/safety/experience story" has
  no cost and no safety in it. 8c runs only if Lane A is green before 15:10.
- **The three PDF deliverables get task bodies and a lane.** 8e diagram already
  had one; **8f README rewrite** and **8g sample inputs/outputs** are new. The
  README currently says *"No application code yet … Java · Spring Boot"* — a judge
  who clones the repo reads a false README. All three are in Lane C, **must start
  by 14:30**, and are done before the deck starts.

Unchanged from the second revision: 8a first, Task 9 third, AWS out (R0),
`experience` dropped from Task 11, R7 promoted.

| # | Task | Lane | Min | Closes |
|---|---|---|---:|---|
| 1 | **8a Action lines** | A | 15 | criterion 1 (35pts) asks it to surface *decisions*; nothing said what to do |
| 2 | **9 Four tools + `/api/ask`** | **C, from 13:00** | 45–60 | criterion 2's "AI solving a genuine problem rather than decorating"; the only place the model *reasons* |
| 3 | 8 Root-cause decomposition | A | 30 | answers *why*, from `delay_reason` |
| 4 | **11 `marshal_compliance` + `cost_per_km`** | A | 30 | cost and safety exist; the T&F head's story has three legs, not one |
| 5 | 10 Replay controls | B | 20 | proactive triggers, visibly |
| 6 | **R1 Sustainability** | A | 15 | the manager's fourth accountability, named twice in the PDF |
| 7 | **R7 Leadership export** | C | 30 | criterion 1's own words: "leadership-ready output, shareable without rework" |
| 8 | 8b Latency instrumentation | A | 15 | criterion 2 names latency; numbers for the deck |
| 9 | **8e Diagram + 8f README + 8g Sample I/O** | **C, start ≤14:30** | 45 | three named deliverables, zero current coverage |
| 10 | **R3 Tenant SLA demo** | A (+ B selector, 15) | 20 | the multi-tenancy bonus, as a screen |
| 11 | 8c Sev-1 anomaly detection | A, **only before 15:10** | 30 | the sixth solution form |
| — | 8d Shift readiness | **→ R9** | — | swapped out; see above |
| — | 12 AWS deployment | **→ R0** | — | unchanged; 16:00 step edits `PROPOSAL.md` §5 to the truth if it did not happen |

### The running order — one developer, agents in parallel by partition

**Pre-condition:** Tier 1 whole-branch review clean and **Task 12R (Render) live**
before the first Tier 2 feature. Then, in this order — the *service* column is the
critical path; console and docs items run alongside it as separate agents:

| Slot | **Service** (`service/`) | **Console** (`console/`) | **Docs / deck** |
|---|---|---|---|
| 1 | **8a action lines** (15) | CostMeter latency line waits for 8b | README/architecture refresh to the deployed state (15) |
| 2 | **Task 9 tools + `/api/ask`** (45–60) | `InterrogationPanel` + `ToolTrace` against a fake trace (45) | — |
| 3 | **Task 8 decomposition** (30) | `CauseBreakdown` (20) | — |
| 4 | **Task 11 marshal + cost/km** (30) | `ReplayControls` (Task 10, 20) | 8e diagram refresh (10) |
| 5 | **R1 EV share** (15) | tenant selector (R3's screen, 15) | — |
| 6 | **8b latency** (15) | latency line in the cost panel (10) | numbers into the deck |
| 7 | **R3 two-tenant SLA** (20) | — | **R7 leadership export** (30, service+console) |
| 8 | 8c anomaly — **only before 15:10** | screenshots of every beat | deck from 15:05 |
| **15:30** | **⛔ ABORT LINE** | screenshots | deck, script, fallbacks |
| 16:00 | **Freeze.** Push. Redeploy Render from `main`. | | `PROPOSAL.md` §5 already says Render — verify |
| 16:15 | Offline rehearsal, beats 1–6 | | |
| 16:30 | **Task 13 demo video — raised to Anshuman** when its gates are green | | |
| 17:00 | **Submit.** | | |

Sequential service minutes: 15 + 60 + 30 + 30 + 15 + 15 + 20 = **185 at 1.0×,
~280 at 1.5×** — 4.6 hours from an 11:00 start lands at ~15:40, so 8c is
already outside the line and R3 is the first thing to drop if Task 9 runs long.
Console and docs items are not on the critical path; they must never make the
service column wait.

### ⛔ 15:30 abort line

Anything not green at 15:30 is **`git revert`ed, not finished.** A half-landed
feature at 16:00 is a broken demo path, a diagram box that lies, and a deck slide
with no screenshot. Allowed after 15:30, and nothing else:

- bug fixes on the eight-beat demo path,
- numbers for slides (latency, cost, cardinalities),
- the `git log -p` credential grep,
- the offline rehearsal.

**Do not start something at 15:30 that takes an hour.** And put a name against
every item by 13:05 — unowned work is what does not get done.

---

### Task 8a: Action lines — what to DO (~15 min) — **do this first**

*Closes the gap in criterion 1, which is **35 points** — the largest on the board.*

The criterion asks: *"Does it meaningfully reduce manager effort or **surface
decisions** that would otherwise be missed?"*

Every finding we produce answers **what** (observed against a reference) and,
after Task 8, **why** (the delay-reason split). **None of them answers what
now.** An independent review grepped this plan for `recommend` and found nothing.
A transport manager reading "vendor X is 27 points below its peers" still has to
decide what to do about it — which is exactly the effort the statement says we
are here to remove.

This is the highest points-per-minute item in the whole build and it was on no
list.

**Files:** `service/signaldesk/actions.py`, `service/tests/test_actions.py`, one
line in the composer, one line in `FindingDto`.

**It must be deterministic.** An action line is a *recommendation attached to a
number*, which is the most consequential sentence in the brief — so it comes from
a table keyed on `(metric_id, tier, cause)`, not from the model. §1.1 holds: the
model may render an action line into prose, never invent one.

- [ ] **Step 1: Write the table**

```python
"""What to do about a finding. Deterministic, keyed on the finding's own fields.

The model never writes these. An action line is the sentence a manager acts on,
and a hallucinated one is worse than none -- so it is a lookup, and the lookup is
tested. The model may re-word an action line when composing prose; it may not
originate one.
"""
from __future__ import annotations

from .schemas import Cause, Finding, Tier

# (metric_id, cause) -> imperative. Tier selects urgency, not content: the thing
# to DO about a lagging vendor is the same at CONCERN and BREACH, only sooner.
_ACTIONS: dict[tuple[str, Cause], str] = {
    ("vendor_ota", Cause.PEER_LAGGARD):
        "Move volume off {slice_value} to the top-quartile vendors at this site, "
        "and put it on the next vendor review.",
    ("vendor_ota", Cause.TREND_REGRESSION):
        "Raise {slice_value}'s decline with the account manager before it reaches "
        "the SLA review -- it is trending, not a one-week blip.",
    ("ota", Cause.BELOW_TARGET):
        "Check the delay-reason split below before escalating: driver delay is a "
        "vendor conversation, employee delay is a comms one, traffic is a routing one.",
    ("otd", Cause.TREND_REGRESSION):
        "Compare the affected shift's release time against cab arrival -- logout "
        "slippage is usually a dispatch-window problem, not a vendor one.",
    ("no_show_rate", Cause.PEER_LAGGARD):
        "Share the no-show list with the line managers for {slice_value}; "
        "confirmed no-shows are billable capacity nobody used.",
    ("sev1_alert_rate", Cause.ANOMALY):
        "Review the Sev-1 events for {slice_value} today -- this is outside the "
        "four-week band, not a normal week.",
    ("marshal_compliance", Cause.BELOW_TARGET):
        "Audit escort sign-ins at {slice_value} for the affected trips. A female "
        "employee cannot board before a marshal signs in, so this is a safety "
        "breach and not a metric miss.",
    ("cost_per_km", Cause.PEER_LAGGARD):
        "Pull {slice_value}'s contract and slab mix against the peer median before "
        "the next billing cycle closes.",
    ("ev_share", Cause.TREND_REGRESSION):
        "Ask the vendor to restore EV allocation at {slice_value}; the fleet mix "
        "moved without a contract change.",
}

# Fallback by cause alone, so a metric added later still says something useful
# rather than nothing.
_BY_CAUSE: dict[Cause, str] = {
    Cause.PEER_LAGGARD: "Compare {slice_value} against the peer median with the "
                        "vendor before the next review.",
    Cause.TREND_REGRESSION: "Look at what changed for {slice_value} in the last "
                            "week -- this is a move against its own history.",
    Cause.BELOW_TARGET: "Escalate {slice_value} against the agreed target.",
    Cause.ANOMALY: "Investigate {slice_value} -- this is outside its normal band.",
    Cause.LOW_CONFIDENCE: "Fix the upstream data for {slice_value} before acting "
                          "on this figure -- we are not confident in it.",
    Cause.DATA_GAP: "This could not be measured. Check the feed before drawing a "
                    "conclusion.",
    Cause.ON_REFERENCE: "",          # a PASS needs no action
}


def action_for(finding: Finding) -> str:
    """The imperative for this finding, or '' when none is warranted.

    A PASS returns '' deliberately -- inventing an action for something that is
    fine is how a brief becomes noise a manager learns to skim.
    """
    if finding.tier is Tier.PASS:
        return ""
    template = (_ACTIONS.get((finding.metric_id, finding.cause))
                or _BY_CAUSE.get(finding.cause, ""))
    if not template:
        return ""
    value = finding.slice.value or "this population"
    return template.format(slice_value=value)
```

- [ ] **Step 2: Attach it, in two places**

- `FindingDto` gains `action: str` — the console renders it under the row, and
  it is the line a manager's eye should land on.
- `TemplateComposer` emits it after each finding's cause line, and
  `SarvamComposer`'s system prompt gains: *"Each finding carries an `action`.
  Reproduce its meaning in your closing sentence. Do not invent an action that is
  not there."*

- [ ] **Step 3: Tests**

```
every (metric, cause) pair in the registry has an action or an explicit blank
a PASS returns an empty string, not a filler sentence
an unmapped metric falls back to the cause-level line rather than returning ''
the slice value is interpolated, and an unsliced finding reads sensibly
LOW_CONFIDENCE tells you to fix the data, NOT to act on the number
the composer's output contains the action line verbatim for a BREACH
```

The fifth is the one that matters. If a `LOW_CONFIDENCE` finding told a manager
to escalate a vendor on a number we have already said we do not trust, the whole
confidence apparatus becomes decorative.

- [ ] **Step 4: Break-it-to-prove-it**

Make `action_for` return the template unformatted (drop `.format`), rerun →
the interpolation test FAILS with a literal `{slice_value}` in the output.
Restore.

Return a filler string for `Tier.PASS`, rerun → the PASS test FAILS. Restore.

- [ ] **Step 5: Read one brief aloud before moving on**

Sweep, compose for `FACILITIES_HEAD`, and read it as the facilities head would.
**Each item should now read: what, against what, why, and what to do.** If the
action lines read as generic filler, rewrite them — a specific wrong action is
better than a vague right one, because the specific one gets corrected and the
vague one gets ignored.

- [ ] **Step 6: Commit** — `feat(actions): deterministic action lines, so a finding says what to do`

---

### Task 8e: Architecture diagram (~15 min) — a named deliverable with no owner

*Closes: §10 of the statement lists **"Architecture diagram"** as a required
deliverable. It had zero minutes allocated and no file.*

**Files:** `docs/architecture.md`

Not a picture — a Mermaid block in a markdown file, which renders on GitHub and
pastes into the deck. Fifteen minutes, and it is on the deliverables list.

- [ ] **Step 1: Draw what was built, not what was planned**

Four layers, with the seam marked. Label the two `[MODEL]` blocks explicitly, and
mark **where SQL is allowed** — that is the invariant made visible, and it is the
single most persuasive thing in the diagram.

- [ ] **Step 2: Include the real numbers**

`615,546 trips · 1.6M legs · 620,942 bill lines · 512,873 ratings · 51,699
alerts` on the ingest layer, and the measured `load_all` time on the edge into
DuckDB. A diagram with real cardinalities reads as a system; one with boxes
labelled "data" reads as a sketch.

- [ ] **Step 3: Delete any box that was cut.** A diagram promising a feature the
demo does not have is worse than a smaller diagram, and it is the artifact a
judge studies while someone else is talking.

- [ ] **Step 4: Commit** — `docs: architecture diagram of what was built`

---

### Task 8f: README rewrite (~15 min) — a named deliverable that is currently false

*Closes: §10 of the statement lists **"README + setup instructions"**. The current
`README.md` L20–29 says "No application code yet … Java · Spring Boot · React".
`AGENTS.md` L36 still points at `data/fixture/`, which was deleted. A judge who
clones the repo reads a false README before they read anything else.*

**Files:** `README.md` (rewrite), `AGENTS.md` (three lines), `OBJECTIVES.md`
(three factual corrections).

- [ ] **Step 1: Rewrite `README.md` top to bottom, in this order.** Every command
  below must be one you have actually run in the last hour — if it is not, run it.

  ````markdown
  # Signal Desk

  An agent that watches enterprise commute operations, works out what a transport
  manager needs to know before they ask, and sends it — with the reasoning and the
  originating SQL attached. **The model never computes a number and never writes SQL.**

  Built for the MoveInSync hackathon (Agentic Intelligence & Reporting Layer for
  Enterprise Mobility), 5 September 2026.

  ## What it does
  Sense → Reason → Compose → Act, on a clock, with no prompt:
  1. A scheduled sweep loads the provided dataset (615k trips, 1.6M rider legs,
     620k bill lines, 513k ratings, 52k alerts) into embedded DuckDB, quarantining
     malformed rows and counting them.
  2. Pure rules compare every metric to its trend, target and peers and emit ranked
     findings with severity, cause, audience and the SQL that produced the number.
  3. Sarvam turns settled findings into a short brief — prose only; the narrative
     is validated against the findings and falls back to a template if it invents a figure.
  4. The brief is routed by severity to Slack and email, and the dispatch is logged.
  A transport manager can then interrogate any finding through four validated
  tools. There is no `run_sql` tool, and a test enforces that.

  ## Architecture
  See [`docs/architecture.md`](docs/architecture.md). One stateless Python service,
  embedded DuckDB, a React console, no backing database or queue.

  ## Prerequisites
  - Python 3.12, Node 22 (`nvm use` reads `.nvmrc`)
  - A Slack incoming webhook (primary delivery), optionally SES sandbox credentials
  - A Sarvam API key (without it the brief ships from the deterministic template)

  ## Run it
  ```sh
  cp .env.example .env          # fill SLACK_WEBHOOK_URL, SARVAM_API_KEY; SES vars optional
  cd service && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
  SIGNALDESK_DATA=../data/real .venv/bin/uvicorn signaldesk.api:app --port 8080
  # in another terminal
  cd console && npm install && npm run dev      # http://localhost:5173, proxies /api to :8080
  ```
  The service sweeps once on startup — watch the log line — and again on its
  schedule. `POST /api/sweep` triggers one by hand; `POST /api/dispatch/{runId}` sends the brief.

  ## Test it
  ```sh
  cd service && .venv/bin/pytest -q      # pytest.ini puts the package on the path
  cd console && npm test
  ```

  ## Data
  `data/real/` — the provided dataset (not committed; see `docs/real-dataset-mapping.md`
  for what is in it and its documented quirks). `data/sample/` — a stratified sample
  the tests run on. Point `SIGNALDESK_DATA` at either.

  ## Sample inputs and outputs
  [`docs/samples/`](docs/samples/) — a real brief, the findings JSON behind it, and
  an excerpt of each input feed.

  ## Repository layout
  `service/signaldesk/` the agent · `console/` the React console · `docs/` design,
  plan, dataset mapping, architecture · `handoff/` the per-lane build briefs · `scripts/` setup.

  ## What we deliberately did not build
  Forecasting, vernacular feedback (the dataset has no free text), auth, a
  historical pipeline, vendor-system integration. See `OBJECTIVES.md`.
  ````

  Delete the "prep that was cleared" section — the tag `prep/pooling-prototype`
  is git history, not README material. Keep the exact env-var names from
  `.env.example`.

- [ ] **Step 2: `AGENTS.md`** — replace the paragraph at L36–39 that describes
  `data/fixture/` (six feeds, 177,072 rows) with one sentence pointing at
  `data/sample/` and `docs/real-dataset-mapping.md`, and delete the "do not
  regenerate the fixture" section (L106 onward) — there is no fixture to regenerate.

- [ ] **Step 3: `OBJECTIVES.md` — verify only.** The three misquotes the judge
  review found (weights cited to `PROPOSAL.md` §4 instead of §7 / PDF §9; M5
  called "disqualifying" when the PDF lists messy-data under good-to-have; a
  "20 free points" quotation that does not exist in `PROPOSAL.md`) were corrected
  on 05 Sep at 00:50 along with the Tier 2 / reserve / clock sync. Grep to confirm
  none crept back: `grep -n 'disqualifying\|20 free points\|PROPOSAL.md. §4' OBJECTIVES.md` → no output.

- [ ] **Step 4: Prove it** — from a fresh clone in `/tmp`, follow the README
  literally. If any command differs from what you typed, the README is wrong, not you.

- [ ] **Step 5: Commit** — `docs: README that describes what exists, with the commands that run it`

---

### Task 8g: Sample inputs and outputs (~10 min) — a named deliverable with nothing behind it

*Closes: §10 lists **"Sample inputs/outputs"**. `handoff/fake-findings.json` exists
but is a fabricated fixture, and a judge can tell. The sample must be real output
from the real dataset.*

**Files:** `docs/samples/README.md`, `docs/samples/input-*.csv`,
`docs/samples/findings.json`, `docs/samples/brief.md`, `docs/samples/dispatch-log.json`

- [ ] **Step 1: Inputs** — the first 25 rows of each of the five real feeds, header
  included, one file per feed, named after the feed (`input-trips.csv`,
  `input-emp-legs.csv`, `input-bill.csv`, `input-feedback.csv`, `input-alerts.csv`).
  Pick rows that show the quirks: at least one `trip_id` in each of the three
  formats, one comma-string epoch, the stray `"False"` severity if it is in the
  first month. `head -26` is not good enough if the first 25 rows are clean —
  `grep` for them.

- [ ] **Step 2: Outputs, from one real run.** After a sweep on `data/real`:
  `curl -s localhost:8080/api/runs/latest/findings > docs/samples/findings.json`;
  the brief as sent, pasted verbatim into `brief.md` with a one-line header saying
  which run and which audience; the dispatch log entry for that send. **Redact the
  webhook URL and any address** before committing — grep the three files for
  `hooks.slack.com` and `@`.

- [ ] **Step 3: `docs/samples/README.md`** — five lines: what each file is, which
  run produced the outputs (runId, window, data path), and the one sentence a judge
  needs: *"Every figure in `brief.md` appears in `findings.json`, and every finding
  carries the `evidence_sql` that produced it — run it in the DuckDB CLI against
  `data/real` to reproduce the number."*

- [ ] **Step 4: Commit** — `docs: sample inputs and outputs from a real sweep`

---

### Task 8: Root-cause gap decomposition (~30 min)

*Closes: criterion 1's "surface decisions that would otherwise be missed".*

Unchanged from the earlier plan — see the task text below. It stays first because
`delay_reason` is a real column, so this is a `GROUP BY` rather than a
derivation, and it is what turns the brief from *what* into *why*.

---

### Task 8b: Latency instrumentation (~15 min) — **cheapest point on the board**

*Closes: criterion 2 names **"inference cost per interaction, latency, efficiency
at enterprise volumes"**. We had cost measured cold and latency merely asserted.*

**Files:** `service/signaldesk/telemetry.py`, `service/tests/test_telemetry.py`,
plus three call sites and one console panel.

A judge reading criterion 2 sees three words: cost, latency, efficiency. Saying
"DuckDB is sub-millisecond" is a claim. **A p95 on 615k real rows is evidence**,
and it is the single highest ratio of points to minutes left in this build.

- [ ] **Step 1: Write the meter**

```python
"""Query and sweep latency, measured rather than asserted.

Criterion 2 names latency explicitly. The DuckDB choice was justified ON
latency -- Athena's ~2s floor per query against sub-millisecond in-process --
so not measuring it leaves the load-bearing argument unevidenced.
"""
from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class LatencyMeter:
    samples: dict[str, list[float]] = field(default_factory=dict)

    @contextmanager
    def measure(self, label: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.samples.setdefault(label, []).append(
                (time.perf_counter() - t0) * 1000.0)

    def stats(self, label: str) -> dict | None:
        xs = sorted(self.samples.get(label, []))
        if not xs:
            return None
        return {
            "n": len(xs),
            "p50Ms": round(statistics.median(xs), 3),
            # index, not interpolation: with n<20 an interpolated p95 invents a
            # value between two real samples. Report a real observation.
            "p95Ms": round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 3),
            "maxMs": round(xs[-1], 3),
        }

    def snapshot(self) -> dict:
        return {k: v for k, v in
                ((label, self.stats(label)) for label in self.samples) if v}


LATENCY = LatencyMeter()
```

- [ ] **Step 2: Instrument exactly three places**

`registry.evaluate` (label `"metric_query"`), `sweep()` (label `"sweep"`), and
`SarvamClient.complete` (label `"model_call"`). Three, not everywhere — a
profiler is not the goal; answering criterion 2 is.

- [ ] **Step 3: Expose it and show it**

Add `"latency": LATENCY.snapshot()` to the `/api/cost` payload (the console's
existing cost panel), and render one line per label: `metric_query p50 0.4ms /
p95 1.2ms (n=312)`.

- [ ] **Step 4: Tests**

```
records a sample per measured call
p95 is greater than or equal to p50
stats() returns None for a label never measured, not a zero
a raising call still records its sample        <- the contextmanager's finally
the sweep label records exactly one sample per sweep
```

The fourth matters: if an exception skips the measurement, your p95 silently
excludes every slow failing query — which is precisely the population you care
about.

- [ ] **Step 5: Get the number that goes on the slide**

Run a full sweep against `data/real` and record `metric_query` p50/p95 and total
sweep duration on 615k trips. **Put those figures in the deck.** If p95 is worse
than a few milliseconds, say the real number anyway — a measured 8ms still
demolishes a 2000ms floor, and an invented 0.2ms is the one number a judge can
catch.

- [ ] **Step 6: Commit** — `feat(telemetry): measure query and sweep latency, which criterion 2 asks for by name`

---

### Task 8c: Sev-1 anomaly detection (~30 min) — closes the last solution form

*Closes: **"insight & anomaly detection"**, the one solution form of six we miss.*

**Files:** `service/signaldesk/references.py` (extend), `schemas.py` (one enum
value), `service/tests/test_anomaly.py`.

The alerts feed is the most differentiated material in the dataset — 52k events,
Sev-1/2/3, `WOMAN_TRAVELLING_ALONE`, `OVER_SPEEDING`. A Sev-1 rate two standard
deviations above its own four-week mean **is** anomaly detection, and the trend
machinery to compute it already exists.

- [ ] **Step 1: Add the reference kind**

`ReferenceKind.TREND_SIGMA`. `_trend()` already evaluates the metric over the
four preceding windows; it currently averages them and throws the spread away.
Keep the spread:

```python
def _trend_sigma(con, metric, slc, window) -> Reference | None:
    """The 4-week mean AND its standard deviation, so deviation can be measured
    in sigmas rather than as a fraction.

    This is what makes it anomaly detection rather than another threshold: a
    Sev-1 rate of 15 per 1k means nothing on its own, and everything if the
    same tenant has run 9.6 +/- 1.1 for a month.
    """
    values = [v for v in (registry.evaluate(con, metric, slc, window.shifted_back(b))
                          for b in range(1, TREND_WINDOWS + 1)) if v is not None]
    # Three points is the floor for a standard deviation that means anything.
    # With two, sigma is the gap between them and every observation is an anomaly.
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    sigma = statistics.stdev(values)
    if sigma == 0:
        return None          # a flat history makes every deviation infinite
    return Reference(ReferenceKind.TREND_SIGMA, mean,
                     f"4-week mean {mean:.2f} +/- {sigma:.2f}")
```

Carry `sigma` on the `Reference` (a new optional field, defaulting to `None`) so
the rule can read it without a second query.

- [ ] **Step 2: The rule — sigmas, not fractions**

In `verdict.py`, when the firing reference is `TREND_SIGMA`, tier on the z-score
instead of the delta bands:

```python
def tier_for_sigma(z: float) -> Tier:
    """|z| thresholds, chosen to match how an ops team reads a control chart.

    Deliberately NOT the delta bands: a fractional threshold on a rate that
    normally sits at 9.6 would fire on a move to 10.1, while 2 sigma on a
    +/-1.1 history means "this has not happened in a month".
    """
    az = abs(z)
    if az < 1.5:
        return Tier.PASS
    if az < 2.0:
        return Tier.WATCH
    if az < 3.0:
        return Tier.CONCERN
    return Tier.BREACH
```

`cause` becomes `Cause.ANOMALY` (new enum value). `gap` stays signed
worse-is-positive: `z * sigma`, so it remains "how far off, in the metric's own
units" and the `PASS`-cannot-carry-a-positive-gap invariant still holds.

- [ ] **Step 3: Apply it to the alerts metrics only, at first**

`sev1_alert_rate` declares `(TREND_SIGMA, PEER)`. Do **not** retrofit
`TREND_SIGMA` onto the on-time metrics in the same sitting — you would be
re-calibrating four metrics at once thirty minutes before freeze.

- [ ] **Step 4: Tests**

```
a value two sigmas above a stable history is a CONCERN
the same absolute value against a volatile history is a PASS   <- the point
sigma of zero omits the reference rather than dividing by it
fewer than three prior windows omits the reference
the z-score sign follows worse-is-positive for a LOWER-is-better metric
gap remains negative for a PASS
```

The second test is the whole idea: **the same number is an anomaly or is not,
depending on the history.** A test that only checks the first case would pass
under a plain threshold and prove nothing.

- [ ] **Step 5: Break-it-to-prove-it**

Replace `statistics.stdev(values)` with a constant `1.0`, rerun. Expected: the
volatile-history test FAILS — it is now just a threshold again. Restore.

- [ ] **Step 6: Say it correctly on stage.** This is "insight & anomaly
detection", the sixth solution form, and it is worth naming as such — but call it
what it is: **a control-chart deviation on a four-week baseline.** Do not call it
machine learning. A judge who asks "what model?" and hears "two standard
deviations" respects the honesty; one who hears "AI-powered anomaly detection"
starts probing.

- [ ] **Step 7: Commit** — `feat(verdict): control-chart anomaly detection on the alerts feed`

---

### Task 8d: The line manager's shift-readiness view (~22 min, reduced scope) — **MOVED TO RESERVE, see R9**

*Closes: persona 3, which the statement names and we were barely serving.*

**Swapped out in the third revision.** The judge review priced it at ~50 real
minutes (roll-up + endpoint + console table, three files across two lanes) for
~2 points, and noted that as scoped it aggregates by shift band while the PDF's
need is "*who* made it, *who* was late" — per-employee. Those minutes buy R1 + R3
(35 minutes, ~4.5 points, both answering things the PDF names). M3 is already
met — the transport manager operates it, the facilities head receives it, and
`audiences_for` already routes shift-sliced findings to `LINE_MANAGER`. The
honest stage line is: *"shift-banded findings route to the line manager today;
the per-employee roll-up is the next sprint, and the 1.6M rider legs are already
loaded for it."* The body below is kept intact so R9 can be started cold.

The statement asks for *"shift-level visibility into who made it, who was late,
and how delays ripple into floor/ops readiness."* That is **per-employee**, and
`emp_legs` carries exactly it across **1.6M rider legs** — `boarding_status`,
`is_no_show`, `not_boarding_reason`, `planned_pickup_at`, `actual_pickup_at`. It
is the largest under-used asset in the dataset.

**Files:** `service/signaldesk/readiness.py`, `api.py` (one endpoint),
`console/src/components/ShiftReadiness.tsx`, tests for both.

**Reduced to 22 minutes on review:** the roll-up, the endpoint, and a plain
table. No amber styling, no sorting controls, no drill-down. Persona 3 needs *a
surface that exists*, not a polished one — and if 15:00 arrives with this
unstarted, cut it. It is the only Tier 2 item whose absence costs a persona rather
than a criterion.

- [ ] **Step 1: The roll-up**

One aggregate per shift band per site, for the window:

```sql
SELECT
  t.shift_band,
  t.site_id,
  count(*)                                                   AS legs_planned,
  count(*) FILTER (WHERE e.boarding_status = 'Boarded')       AS boarded,
  count(*) FILTER (WHERE e.is_no_show)                        AS no_shows,
  count(*) FILTER (WHERE e.actual_pickup_at > e.planned_pickup_at + 300000)
                                                              AS late_pickups,
  -- The "ripple into floor readiness" the statement asks for: the latest
  -- actual pickup in the band is when the floor was actually complete.
  max(e.actual_pickup_at)                                     AS last_arrival_at
FROM emp_legs e JOIN trips t ON t.trip_id = e.trip_id
WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
GROUP BY 1, 2
ORDER BY late_pickups DESC
```

`readiness_pct = boarded / legs_planned`. Findings route to
`Audience.LINE_MANAGER`, which `audiences_for` already assigns to anything
sliced by shift.

- [ ] **Step 2: `GET /api/readiness?runId=latest`** returning that table.

- [ ] **Step 3: `ShiftReadiness.tsx`** — one row per shift band: planned,
boarded, no-shows, late pickups, readiness %, and last arrival as a clock time.
Amber the row when readiness is below 90%.

- [ ] **Step 4: Tests**

```
a boarded leg counts toward readiness and a no-show does not
a pickup exactly on the grace boundary is not late          <- off-by-one
last_arrival_at is the maximum, not the last row scanned
a shift band with no legs is omitted, not rendered as 0%
stwid = 0 placeholder rows are excluded
readiness is null-safe when actual_pickup_at is missing     <- 190k such rows
```

That last one is not hypothetical: `emp_data` has **190,009 null
`actual_pickup_epoch`** values. A leg that was never picked up must not count as
an on-time pickup, and must not crash the comparison.

- [ ] **Step 5: Commit** — `feat(readiness): per-shift floor readiness for the line manager`

---

### Task 9: The four tools and `/api/ask` (~45 min)

*Unchanged. Closes the conversational-agent solution form.* Task text as before.

### Task 10: Replay controls in the console (~20 min)

*Unchanged. The demo's opening beat.*

### Task 11: Cost and safety metrics (~30 min) — **moved up to Tier 2 item 4**

`marshal_compliance` and `cost_per_km`. Each is a registry entry (marshal is
already defined in Task 3's `METRICS`; it needs activating past `TIER_1_METRICS`
and its required-population derivation from `docs/real-dataset-mapping.md` §7)
plus a re-calibration — no new machinery. **`experience` is dropped**: its
ratings include `0` values that may mean *unrated*, so it is the weakest of the
three and the only one needing a judgement call about its own data.

Why this moved ahead of 8c: at 13:00 every live metric is timeliness. The PDF's
strategic persona wants *"a coherent cost/safety/experience story"* — without
this task the story has one leg. `cost_per_km` is `trip_cost / nullif(total_trip_km, 0)`
with trend + peer; marshal is the one hard target in the product. Both columns
exist (`trip_cost`, `total_trip_km`, `actual_escort`, `gender`,
`WOMAN_TRAVELLING_ALONE` alerts). Do `marshal_compliance` first — it is the
safety story and the demo's most quotable finding.

### Task 12R: Deploy to Render (~45 min) — **runs before any Tier 2 feature**

*User's decision 10:05: deploy first, then proceed. Replaces the AWS deploy (R0)
as the deployability story; SES (AWS) stays as the email channel.*

**Files:** `render.yaml`, `service/.python-version` (or `PYTHON_VERSION` env),
`README.md` (deploy section), `docs/architecture.md` (deployment note),
`PROPOSAL.md` §5 (already corrected).

**What is deployed, and with what data.** Render's starter instances have
512 MB RAM; loading the 570 MB real dataset into DuckDB needs several GB, and the
dataset is git-ignored. So the deployed instance runs on **`data/sample`** (3.5 MB,
committed) — the same code, the same sweep, the same brief, smaller numbers — and
**the scored demo still runs on the laptop against `data/real`**, as the plan has
always said. The deployed URL proves deployability, delivery and the model path
from a public host. If a Standard instance (2 GB+) and a persistent disk are set
up later, `SIGNALDESK_DATA` points at the disk and nothing else changes. Say
exactly this on stage if asked which data the URL is on.

- [ ] **Step 1: `render.yaml` blueprint at the repo root** — two services:

```yaml
services:
  - type: web
    name: signal-desk-api
    runtime: python
    plan: starter
    buildCommand: pip install -r service/requirements.txt
    startCommand: cd service && uvicorn signaldesk.api:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /api/health
    autoDeploy: true
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.4"
      - key: SIGNALDESK_DATA
        value: ../data/sample
      - key: SIGNALDESK_CORS_ORIGINS
        sync: false            # set to the console's https URL after the first deploy
      - key: SARVAM_API_KEY
        sync: false
      - key: SLACK_WEBHOOK_URL
        sync: false
      - key: SES_FROM
        sync: false
      - key: SES_TO
        sync: false
      - key: AWS_REGION
        value: ap-south-1
      - key: AWS_ACCESS_KEY_ID
        sync: false
      - key: AWS_SECRET_ACCESS_KEY
        sync: false
  - type: web
    name: signal-desk-console
    runtime: static
    buildCommand: cd console && npm ci && npm run build
    staticPublishPath: console/dist
    autoDeploy: true
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
    envVars:
      - key: VITE_API_BASE
        sync: false            # the api service's https URL
      - key: NODE_VERSION
        value: "22.12.0"
```

  `sync: false` means "set in the dashboard, never in the repo" — a webhook URL
  is a credential. Verify the blueprint keys against the current Render
  blueprint spec before committing (field names have changed between versions:
  `runtime: static` vs `type: static`, `staticPublishPath`, `routes`).

- [ ] **Step 2: Make the service deployable as-is.** `PORT` from the
  environment (uvicorn `--port $PORT` — done by the start command); startup must
  not depend on `.env` existing (`load_dotenv()` is a no-op without the file);
  `/api/health` returns 200 once the startup sweep completes (it does — the
  lifespan runs the sweep before serving). Confirm `data/sample` is committed and
  the path resolves from `service/` (`../data/sample`). Confirm `requirements.txt`
  installs on Linux (no macOS-only pins).

- [ ] **Step 3: Console against a remote API.** `client.ts` already reads
  `VITE_API_BASE`; confirm a production build with `VITE_API_BASE=https://example`
  produces absolute `/api` URLs and that the SPA rewrite serves `/brief`,
  `/health`, `/cost` on refresh (Task 7c's routes).

- [ ] **Step 4: Deploy.** Render dashboard → New → Blueprint → this repo → `main`.
  Fill the `sync: false` env vars. After the first deploy: copy the api URL into
  the console's `VITE_API_BASE` and the console URL into the api's
  `SIGNALDESK_CORS_ORIGINS`; redeploy both. **Prove the deployed pair with the
  laptop service stopped**, so there is no chance of reading a local API.

- [ ] **Step 5: Verify from a shell, and record it in the README**:

```sh
curl -s https://<api>.onrender.com/api/health                 # {"status":"ok",...}
curl -s https://<api>.onrender.com/api/runs/latest/findings | head -c 300
curl -s -X POST https://<api>.onrender.com/api/dispatch/latest  # a Slack message from the cloud
curl -si -X OPTIONS https://<api>.onrender.com/api/runs/latest/findings \
  -H 'Origin: https://<console>.onrender.com' -H 'Access-Control-Request-Method: GET' | grep -i access-control-allow-origin
```

  Open the console URL; it must show a completed sweep, expand to evidence SQL,
  fetch a brief (`source` may be `template` on the sample if the model truncates —
  say which), and dispatch.

- [ ] **Step 6: Docs.** README gets a "Deployed" section with both URLs and the
  sentence about sample vs real data; `docs/architecture.md` gets one line under
  "Data behind one seam". Free-tier caveat: the api spins down after 15 idle
  minutes and cold-starts in ~30–60 s — **warm it before presenting** (already in
  the before-presenting list).

- [ ] **Step 7: Commit** — `feat(deploy): Render blueprint for the service and console`.
  Nothing credential-shaped in `render.yaml`.

**Cost:** starter web service + static site is ~$7/month; the free tier also
works for a demo day, with the cold-start caveat.

## RESERVE — ready to pick up on short notice

Each of these is scoped to be startable cold, in the stated time, by whoever is
free. **Ordered by points per minute.**

**The rule changed in the third revision.** It used to read "do not start one
before Tier 2 is done" — and the judge review showed that, on the arithmetic,
that rule meant none of these would ever be built. So: **R1, R3 and R7 are no
longer reserve — they are Tier 2 items 6, 10 and 7** and their bodies below are
the task text. **R2, R5 and R8 are dropped** — reviewed twice, not worth the
minutes, reasons kept below so nobody re-litigates them at 15:00. What remains
(R0, R4, R6, R9, R10) is the true reserve: pick one only when your lane is green
and it is before 15:10; R4 and R6 are the 15-minute fillers for whoever is idle.

### R0. AWS deployment (~50 min) — **superseded by Task 12R (Render), 10:05 5 Sep. Kept for the reasoning only.**

Its bonus bullet reads: *"Credible deployability story into an existing enterprise
mobility platform — **multi-tenancy, latency, cost**."* The deploy answers none of
those three words. **R3** answers multi-tenancy, **8b** answers latency, and the
cost meter answers cost — all three for 35 minutes between them, against 50 for
the deploy.

What the deploy *does* buy is a URL, and criterion 3 grades *"deployable into an
existing platform"* on structure rather than on a live endpoint: a stateless
service, no backing stores, and the data source behind one seam so local files and
`s3://` are an argument to a function. **That architecture already exists and is
already the answer.**

**But this was an explicit team decision earlier** — AWS credits were obtained for
it, and "targeting AWS" was a stated goal. So it is demoted rather than deleted,
and the call belongs to whoever is running the day, not to this document. If it
goes ahead: give it to the person who is *not* on the critical path, and it must
not displace items 1–7 above.

### R1. Sustainability metric (~15 min) — **PROMOTED to Tier 2 item 6**

The statement's background says the transport manager is *"accountable for cost,
safety, experience, **and sustainability**"*. We answer three of those four and
say nothing about the fourth. `trips.actual_cab_fuel_type` ∈ `Diesel`,
`Electric`, `Petrol`.

```
ev_share = 100.0 * count(*) FILTER (WHERE actual_cab_fuel_type = 'Electric')
           / nullif(count(*), 0)          -- references: trend + peer
```

One registry entry, no new machinery, and it completes the persona's own list of
accountabilities. The PDF names sustainability twice — §3 in the manager's
accountabilities and §4 as one of seven data domains — and until this lands the
plan answers with silence. **Owner: Lane A, 14:30.**

### R2. Industry benchmark reference kind (~15 min) — *reviewed as not worth doing. Dropped.*

M4 is already met three ways (trend, target, peer). The team's own rule below is
"cite or omit", and there is no citable, judge-verifiable published OTA norm for
Indian employee-transport operations — so it resolves to *omit*. Fifteen minutes
of citation hunting for half a point and a liability. Say on stage, if asked:
*"we implement the three reference kinds the data can support; a benchmark we
cannot cite is a number we will not show."*

The statement lists four reference types — *historical trend, SLA/goal, **industry
benchmark**, peer* — and we implement three. Add `ReferenceKind.BENCHMARK`,
sourced from one config dict with a **cited** published figure per metric, and
render the citation in the evidence panel.

**Cite or omit.** An uncited "industry average 88%" is worse than having no
benchmark at all, because it is the one claim a judge can neither verify nor
forgive.

### R3. Multi-tenant SLA demo (~20 min) — **PROMOTED to Tier 2 item 10**

`business_unit` has five real values. Give two of them different targets in
config, run one sweep, and show it producing different findings per tenant.
`DARK_HOURS_BY_SITE` is already this shape. Turns the multi-tenancy bonus from an
argument about interfaces into a screen — and `PROPOSAL.md` §4 itself calls the
in-process engine "a weak multi-tenancy story on its own", so this is the plan
answering its own admitted weakness. **Owner: Lane A at 15:00; Lane B adds the
tenant selector on the findings list (15 min) so it is visibly a screen.**

### R4. Capacity utilisation (~15 min)

`actualemployee_cnt / actual_cab_capacity`, target-referenced. A direct cost
lever a facilities head acts on, and it pairs with `no_show_rate` — under-filled
cabs plus no-shows is one story, not two.

### R5. Alert acknowledgement SLA (~20 min) — *reviewed as not worth doing*

Real, but it measures responsiveness to alerts rather than an outcome, and no
persona in the statement is described as accountable for acknowledgement time.
Skip unless everything above is done and there is an hour spare.

`acknowledge_time − start_time` on `alerts`, with 54 nulls that mean
*unacknowledged* rather than missing. An ops SLA about responsiveness rather than
outcomes, which nothing else here measures.

### R6. Driver / cab non-compliance (~15 min)

`is_driver_nc`, `is_cab_nc`, hard target 0 — reusing the `hard_target` path
already built for `marshal_compliance`. Note these are the columns whose dtype
drifts across the three monthly files, so it also demonstrates `union_by_name`
earning its place.

### R7. Second-persona export (~30 min) — **PROMOTED to Tier 2 item 7**

One-click markdown of the brief for the facilities head — a "Copy for
leadership" button on `BriefPreview` and a `GET /api/runs/{runId}/brief.md`
route. Directly targets the *"forward to leadership without rework"* bonus **and**
criterion 1's own wording, "leadership-ready output, shareable without rework".
"The Slack brief already satisfies it" was the biggest prioritisation error in
the earlier plan: a Slack post is thin as a leadership artifact. **Owner: Lane C
at 14:00, after Task 9; if Task 9 runs long, R7 stops at 14:30 for 8e/8f/8g.**

### R8. Counterfactual (~45 min) — *reviewed as NOT worth doing. Do not build it.*

"Move this vendor's volume to that one" → projected OTA and cost delta.
Memorable, and it was on the earlier list.

**It is an unvalidatable projection**, which is the exact reason we cut
forecasting. We would be claiming a number the data cannot support, in a product
whose entire argument is that every figure on screen is traceable to a query.
A judge who asks "how do you know moving that volume gives that result?" gets an
answer that undermines §1.1.

Cut on principle, not on time. Consistency is worth more than the memorability.

### R9. Shift-readiness view (~22 min service, ~50 real with console) — *moved here from Tier 2 (8d)*

The full body is under **Task 8d** above, unchanged. Start it only if Lane A and
Lane B are both green before 15:00, and only together — a roll-up endpoint with
no table is not a persona surface. If it is built, the stage line stays honest:
shift-banded, not per-employee.

### R10. Vendor escalation draft (~20 min) — *new; the judge's one addition*

The transport manager persona "owns vendor coordination, escalations". Any
BREACH finding sliced by `vendor_id` can produce a **vendor-addressed escalation
draft** from the same composer: add `Audience.VENDOR`, one template ("Your
on-time share for LOGIN trips at {site} was {value}% against a peer median of
{peer}% over {window}; the top cause in our data is {cause} …"), and a "Draft
escalation" button next to the finding. Nothing is sent — it is a draft, copied
to the clipboard. It turns *act* from **informing** into **acting**, which is the
verb criterion 2 uses, for ~20 minutes after Task 6 exists. Worth ~2 points; not
in the running order because Lane A has no slot for it. Whoever is idle after
15:00 with a green lane takes it over R4/R6.

---

## Deliberately NOT on the reserve list

- **Forecasting / predictive risk scoring.** Cannot be done credibly in the time
  and invites a question we cannot answer. Anomaly detection (Task 8c) is the
  honest version of the same instinct.
- **Vernacular feedback translation.** No free-text in the dataset. Cut for
  absence of data.
- **Anything requiring a schema change after 14:00.**

---

## Appendix — full text of the tasks Tier 2 refers to by name

These are the unchanged task bodies. Tier 2 above lists them in the order to
execute; the numbers here match that order, not the order they were written in.

### Task 8 (full text) — Root-cause gap decomposition

Capability 3 of Amendment 1.1, and the cheapest large win here: it turns the brief from *what* into *why*.

**Files:** `service/signaldesk/decompose.py`, `service/tests/test_decompose.py`

Given a finding with a gap, attribute that gap across a dimension: for each value of the dimension, compute the metric and its share of trips, and report how many points of the shortfall that value owns. Pure arithmetic, no model, no I/O beyond the registry.

**Decompose by MoveInSync's own delay taxonomy first, and by vendor/site/shift second.** They already classify every delay in a defined precedence — **Trip Delay → Driver Delay → Employee Delay → Traffic Delay** — where a driver delay means Driver Reporting Time exceeded the first employee's planned sign-in plus grace, an employee delay means actual pickup exceeded planned pickup plus grace, and traffic delay is the residual. See [`docs/moveinsync-domain-vocabulary.md`](../../moveinsync-domain-vocabulary.md) §1.

"OTA is 7 points below trend; 4.1 of those points are driver delay, concentrated in two vendors" is a sentence a MoveInSync transport manager already thinks in. Decomposing only by vendor answers a weaker question and uses our words instead of theirs.

At 10:00, check whether the real dataset carries a delay-reason column and **map its values onto those four buckets** rather than inventing categories. Our fixture's `reason_code` (`TRAFFIC`, `DRIVER_LATE`, `VEHICLE_BREAKDOWN`, `WEATHER`, `GATE_HOLD`) is a usable stand-in but is not their taxonomy. Note the precedence is a cascade, not independent causes: a trip lands in exactly one bucket and the order breaks ties.

```python
def decompose(con, finding, dim) -> list[dict]:
    """Attribute a finding's shortfall across one dimension.

    Returns, per dimension value: observed, share of volume, and points_of_gap —
    how much of the overall shortfall this value owns. Sorted worst first.

    This is what makes the brief say "two vendors own 5.2 of the 7 points"
    instead of "OTA is down 7 points".
    """
```

The contribution of a value is `share_of_volume x (overall_observed - value_observed)`, signed so positive means "this value made it worse". **The contributions must sum to approximately the overall gap** — assert that, with a tolerance, because a decomposition whose parts do not add up is worse than none.

Tests: contributions sum to the whole; a value with tiny volume cannot dominate; the worst contributor is first; a dimension with one value returns one row that owns everything; `points_of_gap` is signed consistently.

Wire it into the finding detail endpoint and the console's expanded row as a small table (`CauseBreakdown.tsx`), and add one clause to the composer's prompt so the narrative can use it.

---

### Task 9 (full text) — The four tools and `/api/ask`

**Files:** `service/signaldesk/tools.py`, `service/tests/test_tools.py`

Exactly four tools: `list_metrics`, `get_metric`, `list_findings`, `explain_finding`. **There is no `run_sql` tool** — that is the deliberate difference between this and a text-to-SQL demo, and it is what makes the answers trustworthy.

Arguments are validated against the enumerations **before** execution. `Dimension.parse` and `registry.by_id` already raise with the valid values named, so the tools catch and return that message rather than re-implementing validation. An unknown dimension is refused by name, never guessed at, never passed to SQL.

The interrogator runs a **bounded** loop — at most four tool calls, then answers from what it gathered. An unbounded tool loop against a 60 req/min tier is how a demo runs out of credits mid-question. Every call appends to a trace, and **the answer is validated against the run's findings with the same validator the brief uses**; a withheld answer still returns its trace, so the verified numbers are visible even when the prose is rejected.

Tests: exactly four tools and none named `run_sql`; an unknown dimension is refused with the valid values named; an unknown metric id likewise; a missing required argument is refused rather than defaulted; the loop stops at four calls; an answer containing a figure no tool returned is withheld; a tool that raises is reported in the trace rather than failing the request; a model outage returns a plain refusal.

`test_invariant.py`: grep `service/signaldesk/` and assert no `SELECT` outside `registry.py` and `ingest.py`, and none at all in `tools.py` or `model.py`. This is the §1.1 invariant enforced mechanically rather than by review — and it is why the module layout is not negotiable.

Then `InterrogationPanel.tsx` + `ToolTrace.tsx`: a question box, the answer, and the tool calls beneath it, expandable to arguments and raw results. Include three suggested questions so a judge does not have to think of one; make the first the worst-vendor question the dataset was built to answer.

**Then ask it something the tools cannot answer** — "what will OTA be next month?" — and confirm it declines rather than inventing a forecast. Forecasting is explicitly out of scope and a judge asking exactly this is likely.

---

### Task 10 (full text) — Replay controls in the console

`ReplayControls.tsx`: start, stop, the current simulated date, and the speed. Poll `/api/runs/latest/findings` while running so **new findings appear on screen as the clock advances.**

This is the beat the demo is built around: *"I am not going to tell you it senses. Watch."* Rehearse it — 60× means a 90-day dataset replays in 90 seconds, which is roughly the right length for a stage.

---

---

### Task 12 (full text) — AWS deployment

**Files:** `infra/Dockerfile`, `infra/apprunner.yaml`, `infra/README.md`

Budget ~$100 of credits, expected to cover two days. **Set a budget alarm at $50 first** — credits do not stop charges by themselves.

- [ ] **Trip logs to S3.** `aws s3 sync data/real s3://<bucket>/trips/`. DuckDB reads them directly via `httpfs`, which is what `source_for()` already abstracts — this is an argument to a function, not a rewrite. That is the multi-tenancy answer made demonstrable.
- [ ] **Service on App Runner** from the `Dockerfile` (python:3.12-slim, `pip install -r requirements.txt`, `uvicorn signaldesk.api:app --host 0.0.0.0 --port $PORT`). App Runner is the shortest path from a working container; Lambda + an ASGI adapter is cheaper at idle. **Pick whichever is already working at 14:00 and stop.**
- [ ] `PORT` must come from the environment. A hardcoded port deploys and then fails its health check with no obvious cause.
- [ ] `healthCheckPath: /api/health`, which reports `degraded` when no metrics are active rather than a 200 that means nothing.
- [ ] **Console to S3 + CloudFront.** `npm run build` with `VITE_API_BASE` set to the App Runner URL, `aws s3 sync dist/ s3://<bucket>/`, CloudFront in front, SPA rewrite to `/index.html` so a refresh on a client-side route does not 404.
- [ ] Set `SIGNALDESK_CORS_ORIGINS` on the service to the CloudFront domain, and **verify with a preflight before opening a browser**: `curl -i -X OPTIONS <api>/api/runs/latest/findings -H 'Origin: <cloudfront>' -H 'Access-Control-Request-Method: GET' | grep -i access-control-allow-origin`
- [ ] **Prove the deployed pair with the laptop service stopped**, so there is no chance of reading a local API.
- [ ] Write `infra/README.md` with the exact commands. If it is not repeatable it is not a deployment story.
- [ ] Confirm no secret and no bucket name reached the repo.

**The scored demo still runs on the laptop.** The AWS URLs exist to make deployability real and to put sponsor infrastructure visibly in use.

# TIER 3 — only if every lane is green before 15:00

There is no separate Tier 3 list any more; it duplicated the reserve and
contradicted it (it listed the counterfactual that R8 says not to build, and the
export and tenant demo that are now Tier 2). **Tier 3 is the reserve**: R10, then
R4, R6, R9 — in that order, and only before 15:10.

One check that costs nothing and is worth doing at 10:00: if the real dataset
carries MoveInSync's `reference_km` (the Google-fastest route computed at trip
end), then `actual_km / reference_km` is a metric whose **reference point ships
with the data**. Cheap if the column exists, impossible if it does not.
`docs/real-dataset-mapping.md` §1 says the trips feed has `total_trip_km` — look
for a second km column before assuming.

**Explicitly NOT Tier 3, and say so if asked:** predictive/forecast risk scoring.
It cannot be done credibly in the budget and it invites a question the build
cannot answer. Spec §2.2 stands.

---

# 16:00 — FEATURE FREEZE. Deck and rehearsal only.

### The demo script — eight beats

1. **"It swept without being asked."** The startup log line.
2. **"Watch it sense."** Start the 60× replay; findings appear live.
3. **"It found this."** The ranked console. Top finding is the worst vendor.
4. **"Here is where the number came from."** Expand the row: references, the rule that fired, `evidence_sql`.
5. **"And here is why."** The cause breakdown — which vendors own how many points.
6. **"Here is what it couldn't read, and it says so."** Feed health, quarantined count, a confidence below 0.9 disclosed in the brief.
7. **"It sent this."** The Slack message, already in the channel.
8. **"And it will defend it."** The interrogation panel with the tool trace visible.

Delete any beat whose feature was cut. **A script promising something the build does not do is worse than a shorter script.**

### Before presenting

- [ ] **One full rehearsal with the WiFi off.** Beats 1–6 must work entirely offline; 7 and 8 need the network, so the script must say so and an earlier Slack message must already be in the channel as the fallback.
- [ ] **A screenshot of every beat in the deck**, in order, as the fallback if the live demo dies.
- [ ] **Edit `PROPOSAL.md` §5's AWS row to the truth** if R0 did not happen — it currently says **Yes**, and a judge holding the proposal against a laptop demo will notice. The honest row: *"Planned — S3 + `httpfs` behind `source_for()` is the deployability seam; the deploy itself was cut for time."*
- [ ] Warm the App Runner URL a few minutes before presenting — **only if R0 happened**.
- [ ] Fill in the real Sarvam pricing, or state that the rupee figure is unconfigured.
- [ ] **Three slides the judge review says will be asked about, and that the build cannot answer without them:**
  1. *"Where is the AI?"* — one slide: sense = scheduled rules; reason = verdict engine + tool-mediated Q&A; act = routed dispatch. The model is the interface and the narrator, and here is why that is the only trustworthy place for it in a system that touches money and safety. Beat 8 (the tool trace, and the refused forecast question) is the demonstration.
  2. *"Why is everything red against 90%?"* — the delay-minutes distribution and the measured OTA, with the sentence: *"90% is the statement's example, not this customer's contract; we rank against trend and peers because those cannot be miscalibrated."*
  3. *"How does this deploy into a Java/Angular multi-tenant platform?"* — the diagram with both seams labelled (`source_for()` → local / S3 `httpfs`; registry → DuckDB today / warehouse adapter tomorrow), the R3 two-tenant screen, and 8b's latency and cost extrapolated to 5k and 50k employees. Then the one-line Java answer from `PROPOSAL.md` §5: six hours, said plainly.
- [ ] Re-check `git log -p` for credentials, **and the deck and every screenshot in it.** A screenshot showing a webhook URL has leaked it.

### Task 13: Demo video (~15 min) — ⏸ **HANDED TO ANSHUMAN, gated**

*Closes: §10 lists **"Demo video (if requested)"**. Zero mentions anywhere in the
team's documents until now. It is conditional in the PDF, so it is worth 0–2
points — but it is also the only insurance against the live demo dying at 19:30
in front of the final jury, and it costs fifteen minutes after the freeze.*

> **For agentic workers: do not execute this task.** When — and only when — every
> gate below is green, **stop and raise it to Anshuman** in one message: the gate
> list with each line ticked, the rehearsal timing, and the sentence "Task 13 is
> ready to record." Then wait. Recording a screen with a live Slack channel and a
> real webhook in it is a human's call, and so is what gets published.

**Gates — all of them, in order, before this is raised:**

- [ ] 16:00 feature freeze has passed and the last push is on `origin`
- [ ] The 13:00 gate is still green on the frozen build (`pytest -q`, `npm test`, unprompted sweep on startup, real Slack send)
- [ ] The offline rehearsal (beats 1–6, WiFi off) has been run once, end to end, and timed
- [ ] Screenshots of every beat are in the deck, in order
- [ ] The credential grep is clean on `git log -p`, **the deck, and every screenshot** — a webhook URL in a frame leaks it
- [ ] `PROPOSAL.md` §5's AWS row says the truth
- [ ] 8e diagram, 8f README and 8g sample I/O are committed (the video will point at them)

**When Anshuman picks it up (16:30, budget 15 min):**

- [ ] **Step 1: Frame.** Console at full window, browser zoom 110% so text survives compression, Slack channel in a second window, no notifications (Do Not Disturb on), no other tabs visible. Run `pytest -q` in a terminal that stays on screen for beat 1's log line.
- [ ] **Step 2: Record with QuickTime (⌘⇧5 → Record Entire Screen, microphone on)**, and talk the eight beats in the demo-script wording, in order. Target **≤ 3 minutes**. One take is fine; two at most — this is insurance, not a product.
- [ ] **Step 3: Check the file** for anything that should not be in it: scrub for the webhook URL, `.env`, email addresses, the Sarvam key in any terminal. If any appears, re-record; do not trim around it.
- [ ] **Step 4: Publish.** Export as `signal-desk-demo-2026-09-05.mp4` at 1080p. Do **not** commit the file — upload it to the team's shared drive and put the link under a `## Demo video` heading at the bottom of `README.md`, with the date and the sentence "recorded from the frozen build at 16:30". Commit that one-line README change. Push.
- [ ] **Step 5: Tell the channel** the link exists, so whoever submits at 17:00 includes it.

If 16:30 arrives and any gate above is red, the video is **not** recorded — the
minutes go to fixing the gate. A video of a broken demo is a liability, not insurance.

### Deliverables checklist

Every line names the task that produces it and the lane that owns it.

- [ ] Source repository, pushed, collaborators added — **Lane A**
- [ ] Architecture diagram reflecting **what was built**, not what was planned; no box for a cut feature — **Task 8e, Lane C, ≤14:30**
- [ ] README with setup instructions a stranger can follow from a fresh clone — **Task 8f, Lane C, ≤14:30**
- [ ] Sample inputs and outputs from a real sweep, redacted — **Task 8g, Lane C, ≤14:30**
- [ ] The deck, with screenshot fallbacks for every beat and the three judge-question slides — **Lane C from 15:05, screenshots from Lane B**
- [ ] Live demo rehearsed once offline, timed — **all, 16:15**
- [ ] Demo video, recorded from the frozen build, linked from the README — **Task 13, Anshuman, 16:30, gated**
- [ ] `infra/README.md` **only if R0 happened**; otherwise `PROPOSAL.md` §5 corrected
- [ ] **Submitted at 17:00** for the early-submission points

---

## Self-review of this plan

**Mandatory-bar coverage.** A working prototype on the provided dataset — Tier 1. Senses, reasons, acts without a prompt — Task 5 (sense), Task 4 (reason), Task 6 (act). A named persona — the transport manager, addressed by name in the brief, with the facilities head as the second recipient. Every metric contextualised against at least one reference point — satisfied by construction in Task 1's `Metric.__post_init__`, not by a feature.

**Scoring coverage.** Business impact (35): the manager stops assembling and starts deciding; the brief is forwardable as-is, which also takes the bonus. Functionality (25): end to end on the real dataset with a real send. Agentic design and cost at scale (20): the loop starts unprompted, aggregation happens in DuckDB, one model call per brief, and the cost meter puts the number on screen. Architecture and code quality (20): one stateless service, no backing stores, clean seams, and the invariant enforced by a grep test.

**Where this plan is weaker than the Java one it replaces**, stated plainly: it has 12 tasks instead of 24, so less of the code is written out in advance and more judgment sits with the implementer on the day. That is the correct trade at six hours — but it means the tests matter more, not less, and `docs/TESTING-LESSONS.md` should be read before Task 2 rather than after something goes wrong.

**What the judge review changed, and what it did not.** It did not touch Tier 1 — the mandatory bar was already covered, and the review's Functionality score is pure execution risk that no plan edit buys down. It changed Tier 2 from a list into three owned lanes with an abort line, because its arithmetic (~390 usable person-minutes against ~390 of planned work at 1.5×) showed the reserve rule was a promise that could not be kept. It gave the three PDF deliverables with no coverage a task each, because a false README is read before any code is. And it added the one task no plan had mentioned — the demo video — as a gated hand-off rather than a build item, because it is insurance for the final jury and a human's call. If a fourth review arrives tonight, the test is the same as for the previous three: does the change answer something the PDF names, and does it fit before 15:30?

**The one thing I would cut first if 13:00 arrives with Tier 1 unfinished:** the Sarvam brief in Task 6. The template brief clears the mandatory bar on its own, and a validated-but-absent narrative costs far less than an incomplete data path. Cut it, ship Tier 1, and add it back at 14:00.
