# Objectives — what we are actually trying to win

**Written 2026-09-04, after the real dataset arrived.** This is the single page
everyone reads before building. It reconciles `PROPOSAL.md`'s goals with the
dataset we now have, and every objective below is stated so you can tell whether
it is met.

Where any other document disagrees with this one about *what we are building*,
this one wins. For *how the data actually looks*, `docs/real-dataset-mapping.md`
wins.

---

## The product, in one sentence

**An agent that watches enterprise commute operations, works out what a transport
manager needs to know before they ask, and sends it — with the reasoning
attached.**

That sentence is from `PROPOSAL.md` and it has not changed through a stack
change, a schema change and a budget correction. It is the thing to protect.

---

## The one decision everything rests on

**The model never computes a number and never writes SQL.**

- **Rules** decide what is wrong, how badly, and who should hear it.
- **A metric registry** answers what the figures are.
- **The model** turns settled findings into language, and answers open questions
  through validated tools.

Three things follow, and they are the whole argument: nothing on screen can be a
hallucinated figure; the reasoning is unit-testable; and prompts stay small
because the model sees aggregates rather than rows, so cost is flat in data
volume.

Do not erode this. If a change would let a model-produced figure reach a screen,
the change is wrong.

---

## Mandatory bar — pass/fail, not scored

The problem statement rules these in. Missing any one of them is
disqualifying, so they come first and Tier 1 exists to satisfy exactly them.

| # | Requirement | How we meet it | Done when |
|---|---|---|---|
| M1 | Working prototype **on the provided dataset** | 615k real trips from `data/real/`, not the synthetic fixture | A sweep over real May–July 2026 data returns ranked findings |
| M2 | **Senses, reasons, acts** — not a passive dashboard or query-only tool | Scheduled sweep fires with no prompt → pure rules emit findings → real Slack/email dispatch | The startup log shows a sweep nobody asked for, and a brief arrives in Slack |
| M3 | Serves a **named persona** | Transport manager operates it; transport & facilities head receives the brief; line manager gets shift-sliced findings | Every brief is addressed to a named role, and audience is assigned by rule |
| M4 | **Contextualises** each metric against a reference point | Every metric declares ≥1 of trend / target / peer, enforced in `Metric.__post_init__` | A metric with no computable reference emits **nothing** rather than a bare number |
| M5 | **Handles messy or missing data gracefully** | Rejects quarantine + per-feed confidence + null-safe arithmetic, against the dataset's *own* documented quirks | Feed health shows non-zero quarantined rows, and a confidence below 0.9 is disclosed in the brief itself |

M5 is worth dwelling on: the dictionary tells us the messiness is **deliberate and
rewarded**. `trip_id` in three formats, epochs as comma-strings, dtype drift
across months, negative distances, a stray `"False"` in `severity`. We do not
merely survive these — we **count them and put the number on screen**.

---

## Scored criteria, and what we are doing for each

Weights from `PROPOSAL.md` §4.

### 1. Business impact & experience — 35 points

The pain named in the statement is sharp: *a metric without context is just a
number.* "OTA is 78%" means nothing. "It was 84.6% last month, the SLA is 90%,
and driver delay at two vendors owns 4.1 of the 7 points" is a decision.

**Objectives:**
- **O1.1** Every finding carries its reference point, its cause, and its
  confidence — never a bare figure.
- **O1.2** The brief is **forwardable without editing** by a facilities head.
  That also takes the bonus criterion.
- **O1.3** Root-cause decomposition answers *why*, using the operator's own
  taxonomy — `delay_reason` ∈ `TRAFFIC / DRIVER / EMPLOYEE`, straight from their
  column.
- **O1.4** The agent says what it **could not** read. A number it is unsure of
  says so.

### 2. Functionality — 25 points

**Objectives:**
- **O2.1** End to end on the real dataset: ingest → metrics → findings → brief →
  **real send**, not a mocked one.
- **O2.2** Six metrics live, each with a real reference point (list below).
- **O2.3** The demo works **with the WiFi off** for every step that can.
- **O2.4** Every figure traceable: `evidence_sql` on every finding, shown in the
  console, runnable in the DuckDB CLI to reproduce the number.

### 3. Agentic design & cost at scale — 20 points

`PROPOSAL.md` calls this "20 free points" because most teams will ignore it.

**Objectives:**
- **O3.1** The loop starts **without a prompt**. The manual trigger exists so a
  judge can watch it fire, not because the loop needs asking.
- **O3.2** A **60× replay clock** so findings appear live on stage. Proves
  proactive triggering instead of claiming it.
- **O3.3** **One model call per brief**, never one per row. Aggregation happens
  in DuckDB.
- **O3.4** A **live cost meter**: measured ~₹0.048/1k tokens, ~₹0.10 per brief,
  **~₹9.50/month for an entire client — flat whether they have 500 employees or
  50,000.** Per-employee cost *falls* as the client grows. A per-row pipeline
  does the opposite, and that contrast is this criterion in one slide.
- **O3.5** The model reaches data only through **four validated tools**. There is
  no `run_sql` tool, and a test enforces that.

### 4. Architecture & code quality — 20 points

**Objectives:**
- **O4.1** One stateless service, no backing database, no queue, no Redis.
- **O4.2** SQL exists in exactly two modules; a grep test enforces it.
- **O4.3** The verdict engine is pure — no I/O, no clock, no model — so the
  reasoning is unit-testable.
- **O4.4** Every guard has been through **break-it-to-prove-it**: delete the
  behaviour, watch the test fail, restore.
- **O4.5** The data source sits behind one seam, so local files and S3 are an
  argument to a function.

### Bonus criteria

- **O5.1 Forwardable artifact** — the leadership brief, sent as-is. Covered by O1.2.
- **O5.2 Multi-tenancy** — **`business_unit` has five real values on every feed.**
  Two tenants with different SLA targets, same sweep, different findings. This
  stops being an argument about interfaces and becomes a screen.

---

## The metric set — real columns, real reference points

Replaces the six invented against the guessed schema. All from
`docs/real-dataset-mapping.md`.

### Tier 1 — by 13:00

| # | id | What | Source | References |
|---|---|---|---|---|
| 1 | `ota` | On-time arrival, **LOGIN** trips | `actual_end_epoch` vs `planned_end_epoch` | trend + target 90% |
| 2 | `otd` | On-time departure, **LOGOUT** trips | same, `trip_direction = 'LOGOUT'` | trend + target 90% |
| 3 | `vendor_ota` | On-time share by vendor | as `ota`, sliced by `vendor_id` (23 vendors) | trend + **peer** |
| 4 | `no_show_rate` | Employees who did not show | `noshow_cnt / plannedemployee_cnt` | trend + peer |

`ota` first because the statement's own worked example is "OTA is 78%". OTA is
**arrival on login trips** and OTD is **departure on logout trips** — MoveInSync's
own split; one metric sliced by direction would put "on-time arrival, logout" on
screen, which is not a thing.

### Tier 2 — after 13:00, in this order

| # | id | What | Source | References |
|---|---|---|---|---|
| 5 | `sev1_alert_rate` | Sev-1 safety alerts per 1,000 trips | `alerts.severity = 'Sev-1'` | trend + peer |
| 6 | `marshal_compliance` | Escort present where required | `actual_escort` over dark-hours trips carrying a female rider, or with a `WOMAN_TRAVELLING_ALONE` alert | target 100%, **hard** |
| 7 | `cost_per_km` | Billed cost per km | `trip_cost / nullif(total_trip_km, 0)` | trend + peer |
| 8 | `experience` | Rider experience | mean of `route/driver/cab/safety_rating`, excluding unrated `0`s | trend |

`marshal_compliance` is the only **hard target**: a female or special-needs
employee cannot board before a marshal signs in, so 99% is not "nearly
compliant", it is a safety failure.

`sev1_alert_rate` is the most differentiated metric available. The alerts feed
(SOS, geofence, over-speeding, `WOMAN_TRAVELLING_ALONE`) is the richest material
in the dataset and most teams will ignore it.

### Dimensions

| Dimension | Column | Values |
|---|---|---|
| `TENANT` | `business_unit` | 5 — the multi-tenancy story |
| `SITE` | `office` | 17–19 |
| `VENDOR` | `vendor_id` (`vendor` in bill) | 23–24 |
| `MODE` | `product_type` | `CAB`, `BUS`, `SPOT_2.0` |
| `DIRECTION` | `trip_direction` (`trip_type` in feedback) | `LOGIN`, `LOGOUT` |
| `SHIFT_BAND` | bucketed from `shift_type` | 4 bands — **never raw; it has 99 values** |

---

## What we are deliberately NOT building

Named so scope creep has to argue against a decision, and so we can say it on
stage as judgement rather than have it found as a gap.

- **Forecasting / predictive risk scoring.** Cannot be done credibly in the
  budget, and it invites a question we cannot answer.
- **Vernacular feedback translation.** **The dataset has no free-text comments** —
  five numeric ratings, no comment column, no language column. Cut for absence of
  data, not for time. We will not run it on synthetic comments beside real data.
- Auth, accounts, RBAC.
- Multi-tenancy *enforcement* — the dimension and per-tenant config exist; row
  isolation does not.
- A historical pipeline, CDC, incremental loading.
- Real vendor system integration.
- Write-back to any operational system.
- Mobile app, PWA, offline sync.
- Audit-log persistence beyond the in-process store.
- Rate limiting, retries, circuit breakers on the model.

---

## Solution forms covered

The statement offers six and asks for two. We hit **five**:

1. **Proactive alerting & triggers** — the unprompted sweep
2. **Automated reporting & narratives** — the validated brief
3. **Conversational agent** — the interrogation panel over four tools
4. **Decision-support dashboard** — ranked findings expandable to evidence
5. **Automated communications** — the Slack and SES dispatch, which the statement
   lists *separately* from automated reporting. An earlier count of four missed
   this.

**Not hit: insight & anomaly detection.** The alerts feed makes it cheap — a
Sev-1 rate 2σ above its own 4-week mean, using the trend machinery that already
exists. It is the highest-value remaining addition and it closes the last form.

---

## The clock

| Time | Gate |
|---|---|
| 10:00 | Point `SIGNALDESK_DATA` at `data/real`; post the real headers to the channel |
| **13:00** | **Tier 1 done.** M1–M5 all satisfied. If not, drop everything else. |
| **16:00** | **Feature freeze.** Deck and rehearsal only. |
| 17:00 | Submit — the early window is worth points by itself |
| 18:00 / 19:30 | Semifinal / final |

## How we know we won

The demo lands if a judge can watch these eight beats without a gap:

1. It swept **without being asked**
2. Watch it sense — the 60× replay, findings appearing live
3. It found this — ranked, worst first
4. Here is where the number came from — `evidence_sql`
5. And here is **why** — delay-reason decomposition
6. Here is what it **could not** read, and it says so
7. It **sent** this — the Slack message, already in the channel
8. And it will **defend** it — the interrogation panel, tool trace visible

**Every beat maps to an objective above.** If a beat has no feature, delete the
beat — a script promising what the build does not do is worse than a short one.
