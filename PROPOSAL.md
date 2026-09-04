# Signal Desk — build proposal

An agent that watches enterprise commute operations, works out what a transport
manager needs to know before they ask, and sends it — with the reasoning attached.

| | |
|---|---|
| Statement | Agentic Intelligence & Reporting Layer for Enterprise Mobility |
| Theme | Agentic AI (Enterprise Mobility / Operations Intelligence) |
| Build day | 5 September 2026 · clock 10:00 · **feature freeze 16:00** · submit 17:00 |
| Usable build time | **~6 hours**, plus ~1 hour deck and rehearsal |
| Stack | Python 3.12 · FastAPI · React 19 · embedded DuckDB · Sarvam `sarvam-105b` · AWS |
| Data | The provided dataset: 615k trips, 1.6M rider legs, 620k bill lines, 513k ratings, 52k alerts (May–July 2026) |
| Team | 3 people, working in parallel from 10:05 against a frozen contract |

**Read alongside:** [`OBJECTIVES.md`](OBJECTIVES.md) for what we are targeting and
how we know it is met; [`docs/real-dataset-mapping.md`](docs/real-dataset-mapping.md)
for what the data actually contains. This file is the *argument*; those two are
the *specifics*.

---

## 1. The problem, in the statement's own words

> *A metric without context is just a number.* "OTA is 78%" matters far less
> than "it was 85% last month, SLA is 90%, and two vendors are responsible for
> the gap."

Transport managers are accountable for cost, safety, experience and
sustainability, and most of their time goes into **assembling** data rather than
acting on it. The signal is rich; the insight is missing; the actions are manual.

Signal Desk runs that second sentence on its own, unprompted, delivers it to the
person who can act, and then defends its answer if challenged.

---

## 2. The product, in one loop

```
SENSE  ──▶  REASON  ──▶  COMPOSE  ──▶  ACT
  │           │            │             │
  │           │            │             └─ Slack + email, routed by severity,
  │           │            │                logging what was sent and on what evidence
  │           │            └─ Sarvam writes the brief over findings already
  │           │               computed — prose only, never arithmetic   [MODEL]
  │           └─ pure rules compare each metric to its reference points and emit
  │              ranked findings: severity, cause, audience, and the SQL behind it
  └─ fires on a clock tick — no human prompt
```

Everything is deterministic and unit-testable except the two blocks marked
`[MODEL]`, which produce language only.

---

## 3. The one decision that determines everything

**The model never computes a number and never writes SQL.**

Rules decide what is wrong and who cares. A metric registry answers what the
figures are. Sarvam turns settled findings into language, and answers open
questions through four validated tools — there is **no `run_sql` tool**, and a
test enforces that.

That split buys three things at once:

- **Nothing on screen can be a hallucinated figure.** The narrative is validated
  against the findings before it is sent; a figure that is not in the findings
  means the brief goes out from a deterministic template instead.
- **The reasoning is unit-testable**, because the verdict engine has no I/O, no
  clock and no model in it.
- **Cost is flat in data volume**, because the model sees aggregates rather than
  rows — which is the cost-at-scale story criterion 2 asks for by name.

It also makes the model layer swappable, which turned out to matter: we run on
Sarvam rather than a frontier model, and because arithmetic never passes through
it, that changes the prose and nothing else.

---

## 4. Why this data layer

Embedded **DuckDB**, no backing services. The question a judge will ask is "why
an embedded database?", and the answer is measured, not aesthetic.

**Latency is the deciding factor, and criterion 2 names it.** Athena has a ~2
second floor per query. The interrogation panel issues several tool calls per
question, so a 2s floor becomes 6–10 seconds before the model writes its first
word. DuckDB runs in-process, sub-millisecond at this size.

**The messy-data feature depends on it.** `read_csv_auto(union_by_name = true,
store_rejects = true)` is what turns "handles messy or missing data gracefully"
into a visible number. Athena needs a schema up front and turns malformed rows
into NULLs; Aurora needs a `CREATE TABLE` and a bespoke loader per file shape.
Either way we lose the feature, not merely the convenience.

`union_by_name` is not hypothetical here: the three monthly trip files **drift in
dtype** — `is_driver_nc` is `bool` in June/July and `object` in May, `planned_km`
is `float` in May/June and `object` in July. That flag is the reason concatenating
them is a non-event.

**Setup time we do not get back.** DuckDB is one pip install. Athena needs an S3
bucket, a Glue table, an IAM policy and a results bucket. That is 30–60 minutes
producing nothing demoable, out of six.

**The honest weakness** is that an in-process engine is a weak multi-tenancy
story on its own. Two things address it: the query layer sits behind a repository
seam, so swapping engines is an adapter rather than a rewrite; and the dataset
carries **`business_unit` with five real values on every feed**, so tenancy is a
dimension we can demonstrate rather than an interface we can point at.

---

## 5. Where we deviate from the statement's preferences, and why

The statement says: *"Open / participant's choice — preferably **Java, Angular,
AWS** resources, but not restrictive."* We are 1 for 3, and it is worth being
straight about that rather than hoping nobody notices.

| Preference | Ours | Honest reasoning |
|---|---|---|
| **Java** | Python 3.12 | An earlier version of this proposal chose Java precisely *because* it is the platform's own language, which converts "deployable into an existing platform" from an argument into a fact. **We gave that up for build speed** when the real ~6-hour budget became clear. It is a real cost under criterion 3, and the mitigation is that the architecture — not the language — is what is portable: a stateless service, a repository seam, no backing stores. |
| **Angular** | React 19 | Team familiarity. Lower cost than the Java swap, since the console is a thin client over a documented HTTP contract and could be rewritten in Angular without touching the service. |
| **AWS** | **Yes** | S3 for the trip logs read directly by DuckDB's `httpfs`, App Runner or Lambda for the service, S3 + CloudFront for the console, SES for email. |

If asked "why not Java?", the answer is six hours, said plainly — not a
retrofitted technical argument.

---

## 6. Requirement coverage

### Mandatory — all four

| Requirement | How |
|---|---|
| Working prototype on the provided dataset | 615k real trips, not a synthetic stand-in |
| Senses, reasons, acts — not passive or query-only | Unprompted scheduled sweep → pure rules → real Slack/email dispatch |
| Serves ≥1 named persona | Transport manager operates; facilities head receives; line manager gets shift-banded findings |
| Contextualises against ≥1 reference point | Every metric declares **trend**, **target** or **peer**, enforced in the type. A metric with no computable reference emits *nothing* rather than a bare number |

### Good-to-have

| | Status |
|---|---|
| Combines ≥2 solution forms | **Five of six** — proactive alerting, automated narrative, conversational agent, decision-support console, automated communications |
| Handles messy/missing data gracefully | Rejects quarantine, per-feed confidence, null-safe arithmetic — against the dataset's *own* documented quirks |
| Proactive triggers rather than on-demand | The sweep fires on a clock tick; a 60× replay clock makes it visible on stage |

**All six are planned.** *Insight & anomaly detection* — the form we originally
missed — is closed by a control-chart deviation on the alerts feed (Sev-1 rate 2σ
above its own four-week mean), which sits in Tier 2 rather than Tier 3. Call it
what it is on stage: a control-chart deviation on a four-week baseline, not
machine learning.

### Bonus

| | Status |
|---|---|
| Deployability — multi-tenancy, latency, cost | Multi-tenancy via `business_unit`; cost measured (~₹0.10/brief, ~₹9.50/month per client, flat in headcount); **latency asserted but not yet measured — see §8** |
| Output a facilities head could forward without rework | The brief is the artifact, addressed to the named role |

---

## 7. Why this scores

| Criterion | Weight | How this answers it |
|---|---|---|
| Business impact & experience | **35** | The manager stops assembling and starts deciding. Output is addressed to a named persona, cites what each figure was compared against, decomposes *why* using the operator's own `delay_reason` taxonomy, and is forwardable as-is — which also takes the bonus. |
| Functionality | **25** | End to end on the real dataset with a real send rather than a mock. Every figure traceable to the SQL that produced it. |
| Agentic design & cost at scale | **20** | The loop starts without a prompt. Aggregation happens in DuckDB, so tokens stay flat as rows grow. One model call per brief, not one per row — measured, and on screen. |
| Architecture & code quality | **20** | One stateless service, no backing stores, clean seams between registry, rules and model, SQL confined to two modules by a test. Weakened by not being Java (§5). |

---

## 8. Known gaps — what we are not covering, and what it costs

Named here so they are decisions rather than discoveries.

1. **Latency is unmeasured.** Criterion 2 names latency explicitly and we
   currently only *assert* sub-millisecond queries. **Cheap fix:** log p50/p95
   query time and put it in the cost panel. Do this — it is minutes.
2. **No anomaly detection.** The one solution form of six we miss. The alerts
   feed makes it cheap: a Sev-1 rate that is 2σ above its own 4-week mean is an
   anomaly, computed with the same trend machinery we already have. **Highest-value
   remaining addition.**
3. **No industry benchmark.** The statement lists four reference-point types and
   we implement three (trend, target, peer). We satisfy the mandatory requirement
   without it, but citing a published industry OTA norm would cost one config
   line and strengthen the "benchmarking is absent today" narrative.
4. **Persona 3 is thin.** The line manager gets shift-banded findings, but the
   statement asks for *"who made it, who was late, and how delays ripple into
   floor readiness"* — which is per-employee, and `emp_data`'s 1.6M rider legs
   carry exactly that (`boarding_status`, `is_no_show`, `actual_pickup_epoch`).
   We barely touch it. The largest under-used asset in the dataset.
5. **"GPS traces" are promised by the statement but absent from the data.** There
   is no GPS ping feed, so the good-to-have's "GPS gaps" example cannot be
   demonstrated literally. Substitutes that *are* real: 190k null actual pickup
   times, `DEVICE_NOT_REACHABLE` and `VEHICLE_STOPPAGE` alerts, 24 negative
   distances. Say this plainly if asked — the data does not contain what the
   statement advertises, and noticing that is itself a point in our favour.
6. **The 90% OTA target does not fit the data.** Measured OTA is 59.1%, so a 90%
   target makes every slice a BREACH and the ranking meaningless. Lean on trend
   and peer, which are derived from the data and cannot be miscalibrated.

---

## 9. Build order

Tiered against ~6 hours, not sequenced against a full day. Full detail in
[`docs/superpowers/plans/2026-09-05-signal-desk-python-build.md`](docs/superpowers/plans/2026-09-05-signal-desk-python-build.md).

| Tier | Contents | Gate |
|---|---|---|
| **Prep** (done, 4 Sep) | Contracts, venv, console scaffold, dataset downloaded and mapped, Sarvam/Slack/SES/AWS verified | ✅ |
| **1** | Ingest + normalisation, registry, verdict engine, sweep, template brief, real Slack send, console | **13:00** |
| **2** | Action lines, cause decomposition, four tools + interrogation, latency, anomaly detection, replay controls, architecture diagram | 16:00 freeze |
| **3** | Reserve items by points-per-minute — sustainability, tenant SLA demo, capacity utilisation | only if 2 completes by 15:00 |

**Tier 1 alone satisfies every mandatory requirement.** That is the point of
tiering: at any moment after 13:00 there is a complete, demonstrable product and
everything after only widens it.

---

## 10. Settled decisions

- **Personas** — transport manager operates it; facilities head receives the
  brief; line manager gets shift-banded findings. Two covered well, one thinly (§8).
- **Real delivery, not drafts** — the agent genuinely sends. SES is in sandbox to
  verified addresses, which is a deliberate channel choice, not a limitation:
  leaving sandbox needs DNS records in place before the request can even be filed.
- **Sarvam as the model layer** — free credits, OpenAI-compatible, and **tool
  calling verified against the live API** before the build. `sarvam-105b`;
  Sarvam-M is deprecated.
- **Demo from the laptop.** Deployed URLs exist to make deployability
  demonstrable; the scored demo depends on neither venue WiFi nor a warm
  container.
- **The fixture is a real slice.** 2.89 MB carved from the provided 572 MB,
  stratified across all five tenants and 23 vendors, join-consistent, with every
  documented quirk preserved. The earlier synthetic fixture was deleted — it was
  built to a guessed schema and would have pinned the wrong contract in tests.

---

## Notes

Every dependency, model id and figure above was verified against upstream
documentation or measured against the real data rather than recalled. That
practice has now caught, among others: `duckdb_jdbc:1.5.5` not existing on Maven
Central, Sarvam-M being deprecated, SES requiring DNS records before a production
request can be filed, epoch timestamps being seconds rather than milliseconds,
`trip_id` appearing in three incompatible formats, and 160 billing rows worth
₹44.6 lakh that belong to no trip at all.
