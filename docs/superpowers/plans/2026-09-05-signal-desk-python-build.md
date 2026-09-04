# Signal Desk — build-day plan (Python)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent that sweeps enterprise commute data unprompted, ranks what a transport manager needs to know against a reference point, explains *why*, and delivers it to Slack and email with the reasoning and the originating SQL attached.

**Architecture:** Four layers, one hard seam. Tolerant CSV ingest into embedded DuckDB with a rejects quarantine; a metric registry that is the only thing holding SQL; pure functions comparing each metric to its reference points and emitting ranked findings; the model turning settled findings into language and answering questions through four validated tools. **No arithmetic passes through the model.**

**Tech Stack:** Python 3.12 · FastAPI · uvicorn · DuckDB 1.5.5 (`duckdb` package) · OpenAI Python SDK against Sarvam · boto3 (SES, S3) · React 19.2 · **Vite 8** · TypeScript 6 · pytest · Vitest 5 + Testing Library

**Spec:** [`docs/superpowers/specs/2026-09-04-signal-desk-design.md`](../specs/2026-09-04-signal-desk-design.md) — **read §15 (Amendment 1.1) first**; it supersedes the body's Java signatures and Render/Vercel deployment.

**Authority above both:** [`docs/MoveInSync-problem-statement.pdf`](../../MoveInSync-problem-statement.pdf).

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
- [ ] **Confirm `aws sts get-caller-identity` returns something tonight.** Account access, MFA and SSO device flows are the other human-latency item: Task 9 needs working credentials, and discovering at 13:30 that your session expired or the account needs an owner's approval costs the whole AWS story. `AWS_REGION` and the credential chain are only needed for Tasks 9 and SES — not for Tier 1.
- [ ] Set an AWS budget alarm at $50 of the $100. Credits do not stop charges by themselves.
- [ ] Add the teammates as repo collaborators — they cannot read any of this otherwise.
- [ ] Whoever is presenting reads `PROPOSAL.md` and spec §15 tonight, not at 18:00.

---

## Work split from 10:05

The contracts in Task 1 exist so four people work in parallel without blocking. **Agree them at 10:05 and do not renegotiate them at 12:00.**

| Owner | Scope |
|---|---|
| **Lead (data)** | Tasks 2–4: ingest, registry, verdict engine. The critical path — nothing downstream is real until `Finding` objects flow. |
| **SDE 1 (frontend)** | Task 7 onward, built against **hardcoded fake `Finding` dicts from minute one.** Do not wait for real data. |
| **SDE 2 (model)** | Tasks 5–6: composer, validator, delivery, tools — also against fakes. |
| **SDE 3 / whoever is free** | Task 9 (AWS) from ~13:00, then the deck and demo script. |

The person on the deck starts at 15:00 at the latest, whatever is unfinished.

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

This is the task that lets four people work at once. It carries five of the eight resolved spec ambiguities directly in code.

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
- [ ] The console opens on a **completed sweep**, rows expand to `evidence_sql`, feed health shows a non-zero quarantined count
- [ ] No credential in `git log -p`:
      `git log -p | grep -iE 'hooks\.slack\.com/services/[A-Z0-9]{5,}|sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}' | grep -v REPLACE`

**Then say the demo out loud in two minutes:** "It swept without being asked. It found this. Here is the query it used. Here is what it couldn't read. It sent this to Slack." If that does not land, the problem is the brief's wording, not a missing feature — and no Tier 2 item fixes it.

**Then write the demo script.** Build only what the script needs from here.

---

# TIER 2 — pick in this order (13:00 → 16:00)

**Reordered 2026-09-04 after judging the proposal against the statement.** The
first four items each close a *named* sub-criterion or solution form. The AWS
deploy has moved **down**: it is ~50 minutes for a story the laptop demo does not
depend on, and it was previously ahead of three things worth more.

Take them in order. **Do not start something at 15:30 that takes an hour.**

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

### Task 8d: The line manager's shift-readiness view (~40 min)

*Closes: persona 3, which the statement names and we were barely serving.*

The statement asks for *"shift-level visibility into who made it, who was late,
and how delays ripple into floor/ops readiness."* That is **per-employee**, and
`emp_legs` carries exactly it across **1.6M rider legs** — `boarding_status`,
`is_no_show`, `not_boarding_reason`, `planned_pickup_at`, `actual_pickup_at`. It
is the largest under-used asset in the dataset.

**Files:** `service/signaldesk/readiness.py`, `api.py` (one endpoint),
`console/src/components/ShiftReadiness.tsx`, tests for both.

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

### Task 11: Remaining metrics (~30 min)

`marshal_compliance`, `cost_per_km`, `experience`. Each is a registry entry plus
a re-calibration — no new machinery.

### Task 12: AWS deployment (~50 min) — **moved down**

*Unchanged in content, demoted in priority.* Everything above closes a named
sub-criterion or solution form; this closes half of one bonus bullet, for a story
the laptop demo does not depend on. Do it if the clock allows, and cut it without
regret if it does not — S3 + `httpfs` behind the source seam is already the
*architecture* of the deployability answer, and that is what criterion 3 grades.

---

## RESERVE — ready to pick up on short notice

Each of these is scoped to be startable cold, in the stated time, by whoever is
free. **Ordered by points per minute.** Do not start one before Tier 2 is done;
do not hesitate if it is.

### R1. Sustainability metric (~15 min) — a gap in the statement's own framing

The statement's background says the transport manager is *"accountable for cost,
safety, experience, **and sustainability**"*. We answer three of those four and
say nothing about the fourth. `trips.actual_cab_fuel_type` ∈ `Diesel`,
`Electric`, `Petrol`.

```
ev_share = 100.0 * count(*) FILTER (WHERE actual_cab_fuel_type = 'Electric')
           / nullif(count(*), 0)          -- references: trend + peer
```

One registry entry, no new machinery, and it completes the persona's own list of
accountabilities. **Best reserve item on this list.**

### R2. Industry benchmark reference kind (~15 min)

The statement lists four reference types — *historical trend, SLA/goal, **industry
benchmark**, peer* — and we implement three. Add `ReferenceKind.BENCHMARK`,
sourced from one config dict with a **cited** published figure per metric, and
render the citation in the evidence panel.

**Cite or omit.** An uncited "industry average 88%" is worse than having no
benchmark at all, because it is the one claim a judge can neither verify nor
forgive.

### R3. Multi-tenant SLA demo (~20 min)

`business_unit` has five real values. Give two of them different targets in
config, run one sweep, and show it producing different findings per tenant.
`DARK_HOURS_BY_SITE` is already this shape. Turns the multi-tenancy bonus from an
argument about interfaces into a screen.

### R4. Capacity utilisation (~15 min)

`actualemployee_cnt / actual_cab_capacity`, target-referenced. A direct cost
lever a facilities head acts on, and it pairs with `no_show_rate` — under-filled
cabs plus no-shows is one story, not two.

### R5. Alert acknowledgement SLA (~20 min)

`acknowledge_time − start_time` on `alerts`, with 54 nulls that mean
*unacknowledged* rather than missing. An ops SLA about responsiveness rather than
outcomes, which nothing else here measures.

### R6. Driver / cab non-compliance (~15 min)

`is_driver_nc`, `is_cab_nc`, hard target 0 — reusing the `hard_target` path
already built for `marshal_compliance`. Note these are the columns whose dtype
drifts across the three monthly files, so it also demonstrates `union_by_name`
earning its place.

### R7. Second-persona export (~30 min)

One-click markdown or PDF of the brief for the facilities head. Directly targets
the *"forward to leadership without rework"* bonus. Lower priority only because
the Slack brief already largely satisfies it.

### R8. Counterfactual (~45 min)

"Move this vendor's volume to that one" → projected OTA and cost delta, built on
Task 8's decomposition. Memorable, and the most likely of these to overrun —
**do not start after 15:00.**

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

# TIER 3 — only if Tier 2 finished before 15:00

- **Counterfactual** — "move this vendor's routes to that one" → projected OTA and cost delta. Builds directly on Task 8's decomposition.
- **Second-persona export** — one-click leadership markdown/PDF, forwardable without rework. Directly targets the bonus criterion.
- **Multi-tenancy made visible** — thresholds already live in `constants.py`; lift them to a per-tenant YAML and show two tenants with different SLAs. **`DARK_HOURS_BY_SITE` is already this shape**, because MoveInSync configures dark hours per city — so the first tenant-scoped setting is done and the pattern is theirs, not ours.
- **Route efficiency against `reference_km`** — if the real dataset carries MoveInSync's `reference_km` (the Google-fastest route computed at trip end), then `actual_km / reference_km` is a metric whose **reference point ships with the data** rather than being derived from trend or peers. The mandatory bar asks for contextualisation against a reference point; this is the strongest possible form of that. Cheap if the column exists, impossible if it does not — check at 10:00.

**Explicitly NOT Tier 3, and say so if asked:** predictive/forecast risk scoring. It cannot be done credibly in the budget and it invites a question the build cannot answer. Spec §2.2 stands.

---

# 16:00 — FEATURE FREEZE. Deck and rehearsal only.

### The demo script — six beats

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
- [ ] Warm the App Runner URL a few minutes before presenting.
- [ ] Fill in the real Sarvam pricing, or state that the rupee figure is unconfigured.
- [ ] Re-check `git log -p` for credentials, **and the deck and every screenshot in it.** A screenshot showing a webhook URL has leaked it.

### Deliverables checklist

- [ ] Source repository, pushed, collaborators added
- [ ] Architecture diagram — reflecting **what was built**, not what was planned. Do not diagram a cut feature.
- [ ] README with setup instructions that someone else can follow
- [ ] Sample inputs and outputs (a fixture CSV excerpt and a real brief)
- [ ] The deck, with screenshot fallbacks
- [ ] Live demo rehearsed once offline
- [ ] `infra/README.md` if Task 9 happened
- [ ] **Submitted at 17:00** for the early-submission points

---

## Self-review of this plan

**Mandatory-bar coverage.** A working prototype on the provided dataset — Tier 1. Senses, reasons, acts without a prompt — Task 5 (sense), Task 4 (reason), Task 6 (act). A named persona — the transport manager, addressed by name in the brief, with the facilities head as the second recipient. Every metric contextualised against at least one reference point — satisfied by construction in Task 1's `Metric.__post_init__`, not by a feature.

**Scoring coverage.** Business impact (35): the manager stops assembling and starts deciding; the brief is forwardable as-is, which also takes the bonus. Functionality (25): end to end on the real dataset with a real send. Agentic design and cost at scale (20): the loop starts unprompted, aggregation happens in DuckDB, one model call per brief, and the cost meter puts the number on screen. Architecture and code quality (20): one stateless service, no backing stores, clean seams, and the invariant enforced by a grep test.

**Where this plan is weaker than the Java one it replaces**, stated plainly: it has 12 tasks instead of 24, so less of the code is written out in advance and more judgment sits with the implementer on the day. That is the correct trade at six hours — but it means the tests matter more, not less, and `docs/TESTING-LESSONS.md` should be read before Task 2 rather than after something goes wrong.

**The one thing I would cut first if 13:00 arrives with Tier 1 unfinished:** the Sarvam brief in Task 6. The template brief clears the mandatory bar on its own, and a validated-but-absent narrative costs far less than an incomplete data path. Cut it, ship Tier 1, and add it back at 14:00.
