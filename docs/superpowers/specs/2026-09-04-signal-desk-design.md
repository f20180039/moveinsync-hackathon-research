# Signal Desk — design spec

**Version:** 1.1 · **Date:** 2026-09-04
**⚠ Read §15 first.** Amendment 1.1 changes the stack, the deployment target and
the scope. Where §15 and the body below disagree, **§15 wins** — the body's Java
signatures and Render/Vercel deployment are superseded and have been left in place
rather than rewritten, because §15 states every delta and the implementation plan
carries the actual code.
**Authority:** [`docs/MoveInSync-problem-statement.pdf`](../../MoveInSync-problem-statement.pdf).
Where this spec and the statement disagree, the statement wins.
**Approved shape:** [`PROPOSAL.md`](../../../PROPOSAL.md) (approach A, signed off).

---

## 1. What this builds

An agent that watches enterprise commute operations, decides unprompted what a
transport manager needs to know, and delivers it with the reasoning attached.

**The mandatory bar is structural, not rhetorical.** The statement rules out "a
passive dashboard or query-only tool". This design clears that because the loop
*starts without a human prompt* — a clock tick or a fresh upload, not a
question.

### 1.1 The invariant

**The model never computes a number and never writes raw SQL.**

- Rules decide what is wrong, how badly, and who should hear it.
- The metric registry answers what the figures are.
- The model turns settled findings into language, and answers open questions
  through validated tools.

Every claim this design makes about trustworthiness, testability, and cost rests
on that split. Do not erode it. If a change would let the model produce a figure
that reaches a screen, the change is wrong.

---

## 2. Scope

### 2.1 In (Tier A — the committed build)

1. Schema-tolerant CSV ingest into embedded DuckDB, with a rejects quarantine
2. Data-gap register producing a per-feed confidence figure
3. Metric registry, six metrics, each declaring its reference points
4. Four-tier verdict engine producing ranked findings
5. Scheduled sweep (the *sense* step) that fires with no prompt
6. Narrative composition via Sarvam over settled findings
7. Real delivery to Slack (webhook) and email (SES sandbox)
8. Manager console: ranked findings, expandable to evidence
9. Interrogation panel: registry exposed to the model as tools
10. Vernacular feedback normalisation feeding the experience metric

### 2.2 Out (Tier C — we commit *not* to build these)

Named explicitly so scope creep has to argue against a decision:

- Authentication, authorisation, user accounts, RBAC
- A historical data pipeline, CDC, or incremental loading
- Real vendor system integration
- Multi-tenancy enforcement (the *interface* exists; the isolation does not)
- Forecasting, ML models, or anomaly detection beyond rolling z-score
- Write-back to any operational system (no dispatch changes, no bookings)
- Mobile app, PWA, offline sync
- Audit log persistence beyond the in-process findings store
- Internationalised UI (feedback is translated; the console is English)
- Rate limiting, retries with backoff, circuit breakers on Sarvam

The statement's own "Not expected" list covers the first three. The rest are
ours, and they are out because they cost hours and win no marks.

---

## 3. The dataset

The provided dataset is **still unseen**. This spec targets a synthetic dataset
built to the shape §6 of the statement describes, and the ingest layer is
schema-tolerant so the real file can replace it as a config change.

### 3.1 Feeds

Six CSV feeds. Column sets are *indicative* — ingest must not require them.

| Feed | Grain | Columns (indicative) |
|---|---|---|
| `trips` | one row per trip | `trip_id, date, shift, mode, site_id, vendor_id, driver_id, vehicle_id, direction, scheduled_at, actual_at, planned_km, actual_km, seats, occupancy, status` |
| `gps_pings` | one row per ping | `trip_id, ts, lat, lng` |
| `delays` | one row per delay event | `trip_id, reason_code, minutes, recorded_at` |
| `costs` | one row per trip | `trip_id, vendor_id, base_inr, km_inr, wait_inr, total_inr` |
| `feedback` | one row per response | `trip_id, employee_id, rating, comment, language` |
| `roster` | one row per employee-shift | `employee_id, site_id, shift, date, expected` |

`mode` ∈ `cab | nodal | shuttle`. `direction` ∈ `login | logout`.
All timestamps epoch milliseconds. All money integer rupees. All durations
minutes. All distances kilometres.

### 3.2 Planted faults — required, not incidental

The generator **must** inject these, because "handles messy or missing data
gracefully" cannot be demonstrated against clean data:

| Fault | Injection rate | What it proves |
|---|---|---|
| GPS trace gaps (missing pings mid-trip) | ~12% of trips | the gap register and confidence figure |
| Unmatched records (`trip_id` in `costs`/`feedback` with no `trips` row) | ~3% of rows | referential tolerance |
| Malformed rows (bad delimiters, wrong types) | ~1.5% of rows | the rejects quarantine |
| Incomplete roster (employees with no matching trip) | ~5% of roster | roster reconciliation |
| Missing `actual_at` (trip never closed out) | ~2% of trips | null-safe metric arithmetic |
| Non-English feedback comments | ~40% of feedback | the translation path |
| One vendor degrading over the final 3 weeks | 1 vendor | **the narrative the demo is built on** |

The last row is the demo. A planted, discoverable regression in one vendor is
what lets the agent say something a manager would act on.

**Determinism:** the generator takes a fixed seed. Same seed, byte-identical
output. No `Math.random()`, no wall-clock reads. Committed to the repo so the
demo is reproducible without regenerating.

### 3.3 Volume

~90 days, ~8,000 trips, 12 vendors, 4 sites, 3 shifts. Large enough for trends
and peer comparison to be meaningful; small enough that every query is
sub-millisecond and the whole fixture fits in git.

---

## 4. Ingest

### 4.1 Loading

One DuckDB view per feed, created with tolerant parsing:

```sql
CREATE OR REPLACE VIEW trips AS
SELECT * FROM read_csv_auto(
  ?,                        -- glob: local path on the day, s3:// in production
  union_by_name = true,     -- merge inconsistent column sets across files
  store_rejects = true,     -- quarantine bad rows instead of dropping them
  rejects_table = 'reject_errors',
  rejects_scan  = 'reject_scans'
);
```

**`ignore_errors` is forbidden.** It has a known defect where it silently drops
*valid* rows, and silent loss is the opposite of what this product claims.
`store_rejects` keeps every failure inspectable.

### 4.2 The rejects surface

`reject_errors` is read back after load and exposed as a first-class number:
count, and per-row the line, column, and error. This appears in the console and
in the brief. **A quarantined row is a finding, not a log line.**

### 4.3 Gap register

A coverage pass per feed produces:

```
FeedHealth {
  feed: String, rowsLoaded: long, rowsRejected: long,
  unmatchedKeys: long, nullCriticalFields: long,
  confidence: double   // 0.0–1.0
}
```

`confidence = 1 - (rejected + unmatched + nullCritical) / totalConsidered`,
clamped to [0,1]. Every finding derived from a feed **carries that feed's
confidence**, and the narrative must mention it when it drops below 0.9. A
number the agent is unsure about must say so.

### 4.4 Data source is pluggable

Reads go through one interface so the engine is unaware of location:

```java
interface TripLogSource { String globFor(Feed feed); }   // local path or s3://…
```

Local files on the day. S3 via `httpfs` in production — pre-cached, so no
mid-demo extension download.

---

## 5. Metric registry

The governed vocabulary. **Nothing else queries raw tables.**

### 5.1 Definition

```java
record Metric(
  String id,                    // "ota"
  String label,                 // "On-time arrival"
  String unit,                  // "%" | "INR" | "min" | "score"
  Direction better,             // HIGHER | LOWER
  String sql,                   // aggregate over one slice, returns one number
  List<ReferenceKind> refs,     // how it is judged
  Double target,                // nullable; required iff refs contains TARGET
  Feed source                   // for confidence attribution
) {}

enum ReferenceKind { TREND, TARGET, PEER }
enum Direction { HIGHER, LOWER }
```

### 5.2 The six metrics

Build order is strict. 1–3 are the spine and must be complete with rules and
golden tests **before** the hour-seven checkpoint. 4–6 land after it.

| # | id | Metric | Unit | Better | References | Target |
|---|---|---|---|---|---|---|
| 1 | `ota` | On-time arrival | % | HIGHER | trend, target | 90 |
| 2 | `sla_breach` | SLA breach rate | % | LOWER | target | 10 |
| 3 | `vendor_ota` | Vendor on-time share | % | HIGHER | trend, peer | — |
| 4 | `cost_per_trip` | Cost per trip | INR | LOWER | trend, peer | — |
| 5 | `night_compliance` | Night-trip compliance | % | HIGHER | target | 100 |
| 6 | `experience` | Employee experience | score | HIGHER | trend | — |

`ota` is metric 1 deliberately: the statement's own worked example is
"OTA is 78%", so it lands with a judge instantly.

**Metric 6 is on the critical path but must degrade.** It depends on the
translation pipeline (§8.3). If feedback is absent or untranslated, it reports
`confidence < 0.5` and the rule emits at most `WATCH` — never a `BREACH` on data
it could not read.

### 5.3 Slices

Enumerated and validated. The model selects from these; it never composes a
join.

```java
enum Dimension { VENDOR, SITE, SHIFT, MODE, DIRECTION, NONE }
record Slice(Dimension dim, String value) {}   // value null iff dim == NONE
```

### 5.4 Reference points

```java
record Reference(ReferenceKind kind, double value, String label) {}
```

- **TREND** — mean of the metric over the preceding 4 complete weeks, excluding
  the window under evaluation. Label: `"4-week average"`.
- **TARGET** — the metric's declared target. Label: `"SLA target"`.
- **PEER** — median across all other values of the same dimension in the same
  window. Label: `"peer median"`. Requires ≥3 peers, else the reference is
  omitted rather than computed on two.

The mandatory requirement is contextualisation against *at least one* reference
point. Every metric here declares one or more, so the requirement is satisfied
by construction, not by a feature.

---

## 6. Verdict engine

### 6.1 Tiers

```java
enum Tier { PASS, WATCH, CONCERN, BREACH }
```

Ordered, compared ordinally, **never summed into a score**. Summing would let
three mild issues outrank one genuine breach.

`CONCERN` exists so that "a vendor is degrading against its own trend" can
outrank "a metric is slightly off target" without either becoming a breach.

### 6.2 The finding record

The unit of everything downstream — the console renders it, the narrative is
written from it, the delivery routes on it.

```java
record Finding(
  String id,                 // stable hash of metric+slice+window
  String metricId,
  Slice slice,
  Window window,             // the period evaluated
  double observed,
  List<Reference> refs,      // every reference evaluated, not just the worst
  Tier tier,
  String cause,              // enum-backed: BELOW_TARGET, TREND_REGRESSION,
                             // PEER_LAGGARD, LOW_CONFIDENCE, DATA_GAP
  double gap,                // signed: observed − the reference that fired
  double confidence,         // inherited from the source feed
  Set<Audience> audiences,   // TRANSPORT_MANAGER | FACILITIES_HEAD | LINE_MANAGER
                             // a SET, not one value: §6.4 assigns two for a
                             // BREACH, and a single field would silently drop
                             // one recipient
  String evidenceSql         // the exact query that produced `observed`
) {}
```

**`gap` is signed and its sign must agree with `tier`.** A `PASS` may never
carry a gap indicating a breach. This is asserted by a test, because a
sign-flipped gap produces a confidently wrong sentence.

**`evidenceSql` is not decoration.** It is what makes a finding auditable and
what the console shows on expand — the answer to "where did this number come
from" is a query the user can read, not a claim.

### 6.3 Rules

One rule per (metric, reference kind). A rule reads a metric's observed value
and one reference, and returns a tier plus a cause. Rules are pure functions of
their inputs — no I/O, no clock, no model.

Thresholds, as fractions of the reference:

Let `delta` be the shortfall against the reference, expressed as a fraction of
the reference and **signed so that positive always means worse**, whichever way
the metric's `better` direction points:

```
delta = better == HIGHER ? (reference − observed) / reference
                         : (observed − reference) / reference
```

| Condition | Tier |
|---|---|
| `delta <= 0.02` (better than the reference, or worse by ≤2%) | `PASS` |
| `0.02 < delta <= 0.05` | `WATCH` |
| `0.05 < delta <= 0.15` | `CONCERN` |
| `delta > 0.15`, or a TARGET missed outright | `BREACH` |
| `confidence < 0.5` | capped at `WATCH`, cause `LOW_CONFIDENCE` |

Defining `delta` this way rather than as "percent worse" removes the sign
confusion that a LOWER-is-better metric like `sla_breach` otherwise invites:
one formula covers both directions, and `Finding.gap` is `delta × reference`,
so its sign agrees with the tier by construction rather than by care.

**These thresholds are provisional and must be re-tuned against the generated
fixture before the golden tests are pinned.** A threshold nobody measured
either fires on everything or nothing. Procedure: run the sweep, print the tier
distribution, and adjust so the fixture produces a mix across all four tiers
with the planted vendor regression landing at `CONCERN` or `BREACH`. Record the
measured distribution in a comment.

### 6.4 Ranking and audience

Findings sort by `(tier desc, |gap| desc, confidence desc)`. Audience is
assigned by rule, not by the model:

- `BREACH` on any metric → `FACILITIES_HEAD` **and** `TRANSPORT_MANAGER`
- `vendor_ota`, `cost_per_trip` → `FACILITIES_HEAD`
- `ota`, `sla_breach`, `night_compliance` → `TRANSPORT_MANAGER`
- anything sliced by `SHIFT` → also `LINE_MANAGER`

---

## 7. The agent loop

### 7.1 Sense

A Spring `@Scheduled` sweep, plus a manual trigger endpoint for the demo. It
iterates every (metric × slice) pair, evaluates rules, and writes findings to an
in-memory store keyed by run id.

**No prompt is involved.** This is the step that satisfies "agentic — senses,
reasons and acts", and it must be visibly automatic in the demo: the manual
trigger exists so a judge can watch it fire, not because the loop needs asking.

The demo drives a **simulated clock**, not wall-clock time, so the same run
always produces the same findings.

### 7.2 Reason

§6. Deterministic, unit-tested, no model.

### 7.3 Compose

One Sarvam call per brief. Input is the ranked findings, serialised compactly —
**never raw rows**. The prompt instructs: write for the named audience, cite the
reference point for each claim, mention confidence where below 0.9, and do not
introduce any figure not present in the findings.

Output is validated before it is sent: every number appearing in the narrative
must match a figure in the findings to two decimal places. **If validation
fails, the brief is sent from a deterministic template instead.** A wrong number
in a leadership brief is worse than plain prose.

### 7.4 Act

Routes by tier: `BREACH` and `CONCERN` → Slack *and* email; `WATCH` → Slack;
`PASS` → console only. Every dispatch records what was sent, to whom, and the
finding ids it was derived from.

---

## 8. Model integration

### 8.1 Client

Sarvam's API is OpenAI-compatible, so the official **OpenAI Java SDK** is used
with a base-URL override:

- Base URL `https://api.sarvam.ai/v1`
- Model `sarvam-105b` (**Sarvam-M is deprecated and no longer served**)
- Auth `Authorization: Bearer <key>`, key from the `SARVAM_API_KEY` environment
  variable only

One `SarvamClient` wrapper; the rest of the code depends on an interface so the
model layer stays swappable — which the invariant in §1.1 makes safe.

### 8.2 Tools for the interrogation panel

The model gets exactly four tools. It cannot reach the database except through
them.

| Tool | Arguments | Returns |
|---|---|---|
| `list_metrics` | — | metric ids, labels, units, references |
| `get_metric` | `metricId`, `dimension`, `value`, `window` | observed, references, confidence |
| `list_findings` | `runId`, optional `tier`, optional `metricId` | ranked findings |
| `explain_finding` | `findingId` | the finding plus its `evidenceSql` and the rule that fired |

Arguments are validated against the enumerations in §5.3 before execution. An
unknown dimension or metric id is rejected with a message naming the valid
values — never guessed at, never passed to SQL.

**There is no `run_sql` tool.** That is the deliberate difference between this
and a text-to-SQL demo, and it is what makes the answers trustworthy.

### 8.3 Translation

Non-English feedback is normalised through Sarvam's translation API before
scoring. The original comment is retained verbatim, and when the narrative
quotes feedback it quotes the original with the translation alongside. Failure
to translate degrades the metric's confidence (§5.2); it never blocks the sweep.

---

## 9. Surfaces

### 9.1 API

```
POST /api/sweep                  trigger a sweep, returns runId
GET  /api/runs/{runId}/findings  ranked findings
GET  /api/findings/{id}          one finding with evidence
GET  /api/health/feeds           FeedHealth per feed
POST /api/ask                    { runId, question } → narrative + tool trace
POST /api/dispatch/{runId}       send the brief
```

Stateless. No session, no auth (§2.2).

### 9.2 Console

React 19 + Vite 8 (Node ≥22.12, pinned via `.nvmrc`). Recharts for
sparklines.

- **Findings list** — ranked, severity encoded in form as well as colour (a
  stripe and a label, not colour alone), each row expandable to observed value,
  every reference, the rule that fired, the confidence, and `evidenceSql`
- **Feed health strip** — rows loaded, quarantined, confidence per feed
- **Interrogation panel** — question box, answer, and the tool calls made,
  shown as a trace so the reasoning is visible rather than asserted
- **Brief preview** — the composed narrative, with a dispatch button

The console opens on a completed sweep, not an empty shell.

---

## 10. Testing

The habits in [`docs/TESTING-LESSONS.md`](../../TESTING-LESSONS.md) apply. The
two that matter most here:

**Break-it-to-prove-it, on every guard.** After a test passes, delete the
behaviour it is named for, confirm the test fails, restore. A test that survives
the removal of its subject is asserting nothing.

**Golden thresholds are measured, then pinned.** Never invented. Land each
golden assertion first as "greater than zero" with the real value logged, then
pin at ~80% of what was measured, recording the measurement in a comment.

Required tests, by layer:

| Layer | Must assert |
|---|---|
| Ingest | a malformed row lands in `reject_errors` and is *counted*, not dropped; `union_by_name` merges two files with different column sets |
| Gap register | confidence falls when faults are injected; is exactly 1.0 on clean input |
| Registry | every metric's SQL returns one number for every valid slice; an invalid slice is rejected |
| References | TREND excludes the evaluated window; PEER is omitted with <3 peers |
| Rules | all four tiers reachable; **`gap` sign agrees with `tier`**; `confidence < 0.5` caps at `WATCH` |
| Ranking | a `BREACH` outranks any number of `WATCH`es — the no-summing property |
| Sweep | deterministic: same fixture and seed produce identical findings |
| Compose | a narrative containing a figure absent from the findings is **rejected** and the template substituted |
| Tools | an unknown dimension is refused with the valid values named; no path reaches SQL without validation |
| Delivery | routing by tier is correct; a send failure does not lose the finding |

---

## 11. Deployment

| Piece | Where | Why |
|---|---|---|
| Console | Vercel | free, trivial; **Vercel has no Java runtime** so it cannot take the service |
| Service | Render, Docker | 750 free instance-hours; supports Java |
| Data | baked into the image | read-only CSVs, so no persistent disk |
| Demo | **the laptop** | Render's free tier spins down after 15 min and a JVM cold start is 30–90s — fine for a link, fatal if a judge clicks it live |

Deployed URLs exist so the deployability story is demonstrable. The scored demo
depends on neither venue WiFi nor a warm JVM. Warm the Render URL before
presenting.

`JAVA_HOME` must point at JDK 21 (`/opt/homebrew/opt/openjdk@21`). Homebrew's
Maven pulls JDK 26 and uses it by default; Lombok and Spring plugins break on it.

---

## 12. Assumptions

1. **The provided dataset resembles §6 of the statement.** If it diverges, the
   cost lands in §5.2's metric SQL — which is why the definitions are
   declarative and few. Whoever receives the dataset posts the column headers
   immediately.
2. **Sarvam supports tool calling as documented.** Verified in the docs;
   **must be confirmed with one real call before the build starts**, because the
   interrogation panel cannot exist without it.
3. Sarvam's free credits cover the build. The architecture makes one model call
   per brief rather than one per row, so a 60 req/min tier is ample.
4. SES sandbox delivery to verified team addresses is acceptable as the email
   proof. Production SES is unreachable in the timeframe.
5. The venue network is unreliable. Every demo path works offline.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Dataset diverges badly from the assumed shape | tolerant ingest; declarative metric SQL; swap definitions before writing rules |
| Sarvam tool calling behaves differently than documented | verify tonight, not at hour ten; the panel is the droppable feature if it fails |
| Six metrics is more surface than three | strict build order; metrics 4–6 land after the hour-seven checkpoint and are individually droppable |
| Metric 6 depends on the translation path | degrades to low confidence rather than failing |
| Model invents a figure | narrative validated against findings; template fallback |
| Thresholds fire on everything or nothing | measured against the fixture before pinning (§6.3) |

---

## 14. Changelog

- **1.1** (2026-09-04) — backend changed to Python, deployment retargeted to AWS,
  three capabilities added (replay clock, cost meter, root-cause decomposition),
  and the time budget corrected against the real event schedule. See §15.
- **1.0** (2026-09-04) — first version. Written after approach A was approved
  and the six-metric, React 19, Render/Vercel and deck decisions were taken.

---

## 15. Amendment 1.1 — stack, budget, deployment, scope

This amendment is authoritative over the body above.

### 15.1 The time budget, which was wrong

A second, independently written proposal supplied the real event schedule for
**5 September 2026**:

| Time | Event |
|---|---|
| 10:00 | Hackathon begins — clock starts |
| 13:00–15:00 | Working lunch (keep building) |
| **16:00** | **Feature freeze (self-imposed)** |
| 17:00–18:00 | Early submission window — scored brownie points |
| 18:00–19:30 | Semifinal, presenting to partner companies |
| 19:30–21:30 | Final jury round |

**Usable build time is ~6 hours, plus ~1 hour for deck and rehearsal.**
`PROPOSAL.md` assumed ~14 h and the first implementation plan estimated ~18 h 55.
Both were wrong, and no ordering of an 18-hour plan ships in six.

Two consequences, and they are the reason this amendment exists:

1. **Scope is now tiered, not sequenced.** A flat task list with a checkpoint
   assumes you know the budget. A tier list degrades gracefully when you do not.
   The plan is restructured accordingly.
2. **The night of 4 September is prep, and prep is where the expensive,
   dataset-independent work goes.** The committed fixture already exists for
   exactly this reason: ingest is schema-tolerant and metric definitions are
   declarative, so 10:00 tomorrow is a *config change*, not a rewrite.

### 15.2 Stack

| Layer | 1.0 | **1.1** |
|---|---|---|
| Service | Java 21 · Spring Boot 3.5 | **Python 3.12 · FastAPI · uvicorn** |
| Data | DuckDB via JDBC | **DuckDB via the `duckdb` Python package** |
| Model client | OpenAI **Java** SDK, base-URL override | **OpenAI *Python* SDK**, `base_url` override |
| Console | React 19 · Vite 7 · TypeScript | React 19.2 · **Vite 8** · TypeScript 6 (what `create-vite` actually installs; same Node floor) |
| Tests | JUnit 5 · AssertJ | **pytest** · Vitest + Testing Library |

Everything in §1.1 survives unchanged: **the model never computes a number and
never writes raw SQL.** That invariant is what makes the stack swappable at all,
and it is the reason this amendment is short rather than a rewrite.

The Java implementation is retired to the annotated tag
`prep/java-spring-prototype`. `data/fixture/*.csv` is kept — CSV is
stack-independent, and those six files carry the seven planted faults of §3.2 and
the V07 three-week regression the demo narrative is built on. Regenerating them
requires JDK 21 and a checkout from the tag; the generator's two load-bearing
pieces (`onTimeProbability`'s planted regression, `FaultInjector`'s rates) are to
be **ported** to Python, not reinvented.

### 15.3 Deployment — AWS, replacing Render and Vercel

§11 is superseded entirely. Budget: ~$100 of credits, expected to cover two days.

| Piece | Where | Why |
|---|---|---|
| Trip logs | **S3** | DuckDB reads them directly via `httpfs`. This was already 1.0's documented production path; it is now the real one, and it puts sponsor infrastructure visibly in use. |
| Service | **App Runner** (container) or **Lambda + API Gateway** (via an ASGI adapter) | Both are inside the credit budget. App Runner is the shorter path from a working `Dockerfile`; Lambda is cheaper at idle. Decide on the day against whichever is already working. |
| Console | **S3 + CloudFront** | Static hosting, pennies, and it removes the cross-provider CORS handshake that Render/Vercel required. |
| Email | **SES, sandbox** | Unchanged from 1.0. Sandbox delivers only to verified addresses; production SES is unreachable in the timeframe. |
| Demo | **the laptop** | Unchanged, and still the right call. Venue network and cold starts are risks a scored demo must not carry. |

`INSTALL httpfs;` must still be run once beforehand so an S3 read cannot try to
download the extension mid-demo.

### 15.4 Added to Tier A — three capabilities, all adopted deliberately

**1. Replay clock at 60×.** §7.1 already drives a *simulated* clock so runs are
reproducible. This extends it: replay the dataset day-by-day at 60× so findings
fire **live on stage**. It converts "the loop starts without a prompt" from a
claim into something a judge watches happen, which is the single highest-value
demo addition available and is nearly free on top of the injected clock.

**2. Live inference cost meter.** Tokens and ₹ per interaction, shown in the
console and extrapolated to 5,000 employees. Criterion 2 ("agentic design & cost
at scale", 20 points) asks for this by name, and 1.0 only argued it in prose. The
architecture makes the number *good*: one model call per brief rather than one per
row, so tokens stay flat as row counts grow.

**3. Root-cause gap decomposition.** Given a metric's shortfall, attribute it
across the slice dimensions — "OTA is 7 points below trend; two vendors own 5.2 of
those points". 1.0 sliced metrics but never decomposed a gap, so the brief could
say *what* but not *why*. Built on the existing `Dimension` enumeration and
reference resolver; the arithmetic is deterministic and unit-tested, so §1.1 holds.

**Still out of scope**, and now explicitly re-confirmed: predictive/forecast risk
scoring. It cannot be done credibly in the budget and it invites a question the
build cannot answer. §2.2 stands.

### 15.5 What did not change

§1.1's invariant, §3's dataset and planted faults, §4's tolerant ingest and gap
register, §5's six metrics and reference kinds, §6's four tiers and signed `gap`,
§7's sense→reason→compose→act loop, §8.2's four tools and the absence of a
`run_sql` tool, §8.3's translation path, §9.1's HTTP contract, §10's testing
requirements, §12's assumptions and §13's risks. The eight deviations recorded in
the implementation plan also stand, including the `gap = delta × reference` sign
resolution and the `hardTarget` reading.
