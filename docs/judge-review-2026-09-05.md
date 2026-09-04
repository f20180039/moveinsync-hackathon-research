# Judge's review — Signal Desk vs. the MoveInSync problem statement

**Written 05 Sep 2026, ~00:45 IST. Build starts 10:00, freeze 16:00, submit 17:00.**
Reviewer stance: adversarial. Ground truth is `docs/MoveInSync-problem-statement.pdf`
(extracted with `pdftotext -layout`), not the team's restatement of it.

**What was reviewed:** the PDF; `PROPOSAL.md`; `OBJECTIVES.md`;
`docs/real-dataset-mapping.md`; `docs/superpowers/plans/2026-09-05-signal-desk-python-build.md`
(2,565 lines — schedule, Tier 1, Tier 2 incl. 8b/8c/8d, RESERVE R1–R8, deliverables checklist);
`handoff/*.md`; `README.md`; `AGENTS.md`; `data/real/Dictionary/*.md`; `git log`;
the code that exists (`service/signaldesk/{ingest,schemas,constants}.py`, tests, console scaffold).

**Build state, verified:** one substantive commit (`f21f986`, tolerant DuckDB ingest).
`PYTHONPATH=. pytest -q` → 25 passed, 1 skipped (a bare `pytest` fails at collection —
`signaldesk` is not on the path and nothing documents the invocation). `console/src/App.tsx`
is the Vite hello-world. No registry, verdict engine, sweep, API, composer, delivery, tools,
console components, deck, diagram or `infra/` exist. **This is a plan review.** Every "five of
six solution forms" / "all mandatory met" sentence in the team's docs describes the plan, not
the repo.

---

## 1. Requirement-by-requirement conformance

Verdicts are against **what will plausibly exist at 17:00 if the plan executes as written**,
with build-state caveats. Legend: MET / PARTIAL / MISSED / CLAIMED-BUT-UNPROVEN (CBU).

### 1a. Mandatory (PDF §8)

| # | PDF requirement | Where the team addresses it | Verdict |
|---|---|---|---|
| M1 | "Working, demo-able prototype running on the provided dataset" | `OBJECTIVES.md` M1 (L51); plan Tier 1 + 13:00 gate (L2003–2020); `ingest.py` already reads `data/real` globs | **CBU.** Only ingest exists. Tier 1 remaining (Tasks 3–7) sums to ~255 estimated minutes; the critical path (Tasks 3→4→5) is ~140 min sequential on one person before anything is demoable. Achievable by 13:00 only with zero slippage. |
| M2 | "Agentic behaviour — senses, reasons, and acts; not a passive dashboard or query-only tool" | `PROPOSAL.md` §2–3; `OBJECTIVES.md` M2, O3.1; plan Task 5 (sweep on startup, replay clock), Task 6 (dispatch) | **PARTIAL (design) / CBU (code).** Sense = scheduled rules sweep; Reason = deterministic verdict engine; Act = Slack/SES post. Structurally clears the bar. But see §5 Q1: the *model* neither senses nor reasons nor acts — it writes prose, and the plan's own fallback (L2563–2565) ships without it. A judge reading criterion 2's "AI solving a genuine problem rather than decorating" will push here. |
| M3 | "Serves at least one of the three named personas" | `OBJECTIVES.md` M3; plan `audiences_for` (L1408–1419); Task 8d | **MET (by design).** Transport manager + facilities head routing is Tier 1. Line manager is Tier 2 (8d) and, even built, aggregates by shift band — see persona row below. |
| M4 | "Contextualises metrics against at least one reference point (historical trend, SLA/goal, industry benchmark, or peer comparison)" | `Metric.__post_init__` enforcement (`schemas.py`); `OBJECTIVES.md` M4; three of four kinds (trend/target/peer) | **MET (by design).** Industry benchmark is R2 — see §4: drop it. |

### 1b. Good-to-have (PDF §8)

| # | PDF requirement | Where addressed | Verdict |
|---|---|---|---|
| G1 | "Combines two or more of the solution forms listed in Section 7" | `PROPOSAL.md` §6 ("Five of six"); `OBJECTIVES.md` L227–246 | **CBU.** At Tier 1 close: alerting, narrative, dashboard, communications = 4. Conversational agent (Task 9) and anomaly (8c) are Tier 2. Two forms is the bar; the bar will be cleared. "Five of six" is a plan claim. |
| G2 | "Handles messy or missing data gracefully (GPS gaps, unmatched records, incomplete rosters)" | `ingest.py` rejects quarantine, `UNMATCHED_SQL`, `CRITICAL` null counts; `OBJECTIVES.md` "M5" | **MET for what the data allows.** Unmatched records: yes (`_unmatched`). Incomplete rosters: yes (190k null `actual_pickup_epoch`, `stwid=0`). GPS gaps: **no GPS data exists** (`real-dataset-mapping.md` §1) — not a gap, close it, and say so on stage as `PROPOSAL.md` §8.5 already plans. This is the one area where the code already outruns the claim. |
| G3 | "Proactive triggers rather than purely on-demand responses" | Task 5 startup sweep + `ReplayClock`; Task 10 console controls | **CBU.** Design is right. Task 10 (the "watch it sense" beat) is Tier 2 item 6 of 8 — at risk of being cut, which would reduce "proactive" to a startup log line. |

### 1c. Bonus (PDF §8)

| # | PDF requirement | Where addressed | Verdict |
|---|---|---|---|
| B1a | "Credible deployability story … **multi-tenancy**" | `PROPOSAL.md` §4 ("honest weakness"), §6; `OBJECTIVES.md` O5.2; **R3 in RESERVE** (plan L2372) | **PARTIAL → likely MISSED.** The PDF names multi-tenancy by name; the plan answers with a `TENANT` dimension and an argument. The thing that makes it a screen (two tenants, two SLAs, one sweep) is a reserve item that, per the plan's own rule ("Do not start one before Tier 2 is done"), will not be built (see §4 arithmetic). |
| B1b | "… **latency**" | Task 8b (plan L2044–2143); `PROPOSAL.md` §8.1 admits "asserted but not measured" | **CBU.** Cheap, correctly prioritised. Keep. |
| B1c | "… **cost**" | Task 6 `CostMeter`; measured Sarvam rate (plan L279–298) | **MET (by design).** Best-evidenced bonus item. Note the caveat the plan itself records: reasoning tokens are billed and may be under-counted (L295–298). |
| B2 | "Output a transport & facilities head could forward to leadership without rework" | `OBJECTIVES.md` O1.2/O5.1; brief addressed to `FACILITIES_HEAD`; **R7 export in RESERVE** | **PARTIAL.** A Slack message with `*[BREACH]*` markdown is forwardable but is not "leadership-ready" in the sense criterion 1 uses ("leadership-ready output, shareable without rework"). No PDF/markdown/email-formatted artefact exists in Tier 1 or Tier 2. SES email (Task 6) partially covers it if the email body is formatted for a reader, not a channel. |

### 1d. Solution forms (PDF §7) — each as its own row

| Form | Where | Verdict |
|---|---|---|
| Conversational agent (NL Q&A) | Task 9, four tools, `/api/ask`, `InterrogationPanel` | **CBU — and unowned.** `handoff/README.md` gives Anshuman `service/signaldesk/` (data spine), Teammate A `console/`, Teammate B `delivery.py` + deck. `tools.py`/`/api/ask` (45 min) is in nobody's lane, and the "own your directory, never edit outside it" rule forbids Teammate B from taking it. This is the single most important gap in the running order. |
| Proactive alerting & triggers | Task 5 sweep, Task 6 dispatch by tier | **CBU** (Tier 1). |
| Automated reporting & narratives | Task 6 `sarvam_brief` + `template_brief` + validator | **CBU** (Tier 1). |
| Insight & anomaly detection | Task 8c control-chart on Sev-1 rate | **CBU** (Tier 2 item 3). |
| Decision-support dashboard | Task 7 console, ranked findings → `evidence_sql` | **CBU** (Tier 1). |
| Automated communications | Slack + SES routed by `audiences_for` | **CBU** (Tier 1). |

### 1e. Personas (PDF §3) — what the PDF says each one *needs*

| Persona | PDF's stated need | Where | Verdict |
|---|---|---|---|
| Transport manager | "vendor coordination, escalations, shift planning, delay management. Needs fast, actionable signals" | Findings sliced by vendor; `delay_reason` decomposition (Task 8) | **PARTIAL.** Signals: yes. "Escalations" / "vendor coordination": the agent never produces a vendor-addressed artefact; the loop ends at informing the manager. Cheap fix in §5 Q1. |
| T&F head | "budget, SLA accountability, vendor strategy, leadership reporting. Needs a coherent cost/safety/experience story" | Brief addressed to `FACILITIES_HEAD` | **PARTIAL.** At 13:00 the metric set is `ota`, `otd`, `vendor_ota`, `no_show_rate` — **all timeliness**. Cost (`cost_per_km`), safety (`marshal_compliance`, `sev1_alert_rate`) and experience are Tier 2 (Task 11 / metrics 5–8). If Tier 2 slips, the "coherent cost/safety/experience story" the PDF names for this persona does not exist. Task 11 is under-prioritised (item 7 of 8). |
| Team / line manager | "shift-level visibility into **who made it, who was late**, and how delays ripple into floor/ops readiness" | Task 8d (plan L2253–2315) | **PARTIAL even if built.** 8d aggregates per shift band × site (counts, readiness %, last arrival). "Who" is per-employee; `emp_data` has `stwid`, `is_no_show`, `boarding_status`, `actual_pickup_epoch` per leg — the data supports a named list and 8d does not produce one. |

### 1f. PDF §4 data domains the statement enumerates

"ops scale, timeliness/delays, safety/compliance, cost, sustainability, employee experience, vendor performance."

| Domain | Planned coverage | Verdict |
|---|---|---|
| Timeliness/delays | Tier 1 (4 metrics) + Task 8 | MET |
| Vendor performance | `vendor_ota`, peer reference | MET |
| Safety/compliance | Tier 2: `sev1_alert_rate`, `marshal_compliance`; R6 | CBU |
| Cost | Tier 2: `cost_per_km` | CBU |
| Employee experience | Tier 2: `experience` (ratings) | CBU |
| **Sustainability** | **R1 only** (reserve). PDF §3 also lists it in the transport manager's four accountabilities. `actual_cab_fuel_type` ∈ Diesel/Electric/Petrol exists (`Dictionary/ride_data_trip.md` L34) | **MISSED under the plan's own rules** — see §4, promote. |
| **Ops scale** | Nothing. R4 capacity utilisation is the nearest (`actualemployee_cnt / actual_cab_capacity`, both exist) | **MISSED.** Low cost to a judge; low points. |

### 1g. Tech stack preference (PDF §5) and deliverables (PDF §10)

| Item | Where | Verdict |
|---|---|---|
| "preferably Java, Angular, AWS" | `PROPOSAL.md` §5: "1 for 3" (AWS yes) | **CLAIMED-BUT-UNPROVEN → likely 0 for 3.** AWS deploy is Task 12, last in Tier 2, "cut it without regret". If cut, `PROPOSAL.md` §5's table is false at submission. Either build it or rewrite the row before 16:00. |
| Source code repository | exists locally; plan L2546 "pushed, collaborators added" | CBU — not confirmed pushed. |
| **Architecture diagram** | plan L2547, `delivery-brief.md` L189 — a checkbox. `grep -i mermaid\|diagram` over the spec: **zero hits.** Only the ASCII loop in `PROPOSAL.md` §2. | **MISSED as of now.** Nobody owns it before 15:00. |
| **README + setup instructions** | `README.md` L26–33: "**No application code yet, and no design spec.** … Direction so far: **Java · Spring Boot · React**" | **MISSED — actively wrong.** It also does not say `PYTHONPATH=.`; a judge who clones and runs `pytest` sees two collection errors. `AGENTS.md` L37–39 likewise says "What exists as code: nothing yet" and cites a deleted `data/fixture/` (177,072 rows). |
| Sample inputs/outputs | plan L2549 checkbox; `handoff/fake-findings.json` is a fake, not an output | **MISSED as of now.** 10 minutes once a real brief exists. |
| **Demo video (if requested)** | **Zero mentions** in any team document (`grep -ri video` → nothing) | **UNMENTIONED.** "If requested" — but nobody has planned a 3-minute screen recording as insurance. |
| Presentation deck | `delivery-brief.md` Part 2 from 15:00; no `deck/` exists | CBU — planned, correctly owned. |
| Live demo | 8 beats, offline rehearsal, screenshot fallbacks | CBU — planned well. Beats 2, 5, 8 depend on Tier 2 items (Tasks 10, 8, 9). |

### 1h. Where the team's restatement misquotes or reweights the PDF

1. **`OBJECTIVES.md` L44–55 promotes "Handles messy or missing data" to mandatory ("M5 … Missing any one of them is disqualifying").** The PDF lists it under *Good-to-have*. Safe direction, wrong fact — and it inflates the 13:00 gate: the plan will hold Tier 1 for a non-mandatory item.
2. **`OBJECTIVES.md` L66: "Weights from `PROPOSAL.md` §4."** §4 is the data-layer section; the weights are in §7. The weights themselves (35/25/20/20) match the PDF.
3. **Criterion numbering differs between documents.** PDF: 1 Business, 2 Agentic & cost, 3 Architecture, 4 Functionality. `OBJECTIVES.md` renumbers: 1 Business, 2 Functionality, 3 Agentic, 4 Architecture. `PROPOSAL.md` §8 and the plan say "criterion 2 names latency" (PDF-correct). On stage, use the PDF's numbering only.
4. **`OBJECTIVES.md` L97: "`PROPOSAL.md` calls this '20 free points'."** That phrase does not appear in `PROPOSAL.md`.
5. **Plan L168: "four people work in parallel"; L173 "SDE 3 … Task 9 (AWS)"; L2554 "`infra/README.md` if Task 9 happened".** There are three people (`PROPOSAL.md` L14, `handoff/README.md`), and Task 9 is now the tools, Task 12 is AWS. Stale cross-references in the document three people will execute from.
6. **`PROPOSAL.md` §6 "Five of six" and `OBJECTIVES.md` L229 "We hit five"** — present tense for things that are Tier 1/Tier 2 plan items with zero code behind them.
7. **`PROPOSAL.md` §6 "Handles messy/missing data … against the dataset's *own* documented quirks"** is the one claim the code already partly supports (`ingest.py` normalisation, rejects, unmatched) — credit where due.

---

## 2. Judge's scorecard

Scored against the PDF's criteria and weights, for the **likely 17:00 state**: Tier 1 lands
~13:30, Tasks 8, 8b land, Task 9 lands late or not at all, Tasks 10–12 partially cut, no reserve
item built, deck done from a rushed 15:00 start. Where Tier 1 fails outright, halve everything.

| # | Criterion (PDF) | Max | Score | One-line reason | What the next 5 points cost |
|---|---|---|---|---|---|
| 1 | Business impact & experience — "reduce manager effort or surface decisions that would otherwise be missed — and does it land? Clarity for the intended persona, leadership-ready output, shareable without rework" | 35 | **23** | The brief-with-reasoning is exactly the pain the PDF names, and `delay_reason` decomposition answers *why*. Loses points because (a) at Tier 1 close it is a timeliness-only product, (b) the 90% target makes every slice BREACH unless the calibration step actually fires (`real-dataset-mapping.md` §10b), (c) the forwardable artefact is a Slack post, (d) sustainability — named in the persona's own accountability list — is silent. | Task 11 cost+marshal metrics (30 min) + R1 (15) + R7 markdown export (30) + verified data-derived OTA target (15) = **~90 min → +5** |
| 2 | Agentic design & cost at scale — "AI solving a genuine problem rather than decorating … Inference cost per interaction, latency, efficiency at enterprise volumes" | 20 | **13** | Cost meter, one-call-per-brief, flat-in-rows is a genuinely good answer to the second half. The first half is the exposure: by the team's own design the model "produces language only" and the template fallback ships without it — a judge can call that decoration. Task 9 (bounded tool-calling Q&A, refuses forecasts) is the only thing that makes the AI load-bearing, and it is unowned. | Task 9 landed and demoed (45–60 min) + 8b latency numbers on a slide (15) + one slide "what the model does / does not / why" (10) = **~80 min → +5** |
| 3 | Architecture & code quality — "sound structure and engineering judgement; deployable into an existing platform; choices a team could build on" | 20 | **12** | The seams (registry / rules / model; SQL confined by a grep test; pure verdict engine; injected clock) are the strongest engineering in the plan and are test-enforced. Loses on: Python not Java (self-admitted), embedded DuckDB as the multi-tenancy story, no diagram, a README that says Java and "no code", tests that only run with an undocumented `PYTHONPATH`, and an AWS story that is Tier 2 item 8. | Architecture diagram of what was built (20) + README rewrite incl. run/test commands (15) + R3 two-tenant config screen (20) = **~55 min → +5**. AWS (50 min) buys ~2 and does not fit. |
| 4 | Functionality — "It runs — a working, demo-able prototype, end to end, on the provided dataset" | 25 | **16** | Ingest on the real 615k trips is real and tested. Everything else is 255 estimated minutes away with a 140-minute sequential critical path on one person, and the console is hello-world. If Tier 1 lands by ~13:30 with a real Slack send this is ~19; if the sweep produces a wall of BREACH or the send fails live, ~12. | Nothing to buy — this is execution. The +5 is "Tier 1 green at 13:00 and one offline rehearsal by 15:45". Protect it by refusing Tier 2 starts until the gate checklist (plan L2008–2017) is fully ticked. |
| | **Total** | **100** | **64** | | |

**Blunt placement:** as planned-and-likely-delivered this is a **solid upper-middle entry — a
probable semifinalist, not a probable finalist**. The architecture argument is the best thing in
the room; the risk is that at 17:00 the judges see a timeliness dashboard with a Slack post and
a stale README, and the argument stays in the deck. A top-three finish needs three things that
are all currently at risk: Tier 1 green by 13:30, Task 9 live, and the deliverables (diagram,
README, sample I/O) done by someone before 15:00 rather than "in the checklist".

---

## 3. The misses, triaged by points per minute

Points are my estimate of recoverable score under the PDF's criteria. Minutes are the plan's
estimate where one exists; where I disagree I say so. Fit = fits the 13:00–16:00 window given
the budget arithmetic in §4 (**~390 realistic person-minutes, of which planned Tier 2 already
consumes ~390 at a 1.5× multiplier**). Data column = does the dataset carry what it needs
(checked against `data/real/Dictionary/*.md`).

| Rank | Gap | Costs points under | Pts | Min | Fit | Data needed / exists? |
|---|---|---|---|---|---|---|
| 1 | **Verify the OTA/OTD target is data-derived, not 90%** (else every slice is BREACH and ranking is meaningless — `real-dataset-mapping.md` §10b) | C1 (ranking is the product), C4 | 3 | 15 | YES — it is inside Task 4's calibration step already; make it a named gate item | `actual_end_epoch`, `planned_end_epoch` — exist |
| 2 | **Architecture diagram** — deliverable; none exists anywhere | C3 + deliverable | 3 | 20 | YES | none |
| 3 | **README rewrite** — currently says Java, "no application code", no run/test commands | C3 + deliverable | 2 | 15 | YES | none |
| 4 | **R1 EV share** — PDF §3 and §4 both name sustainability; plan is silent | C1 | 2 | 15 | YES | `actual_cab_fuel_type` (Diesel/Electric/Petrol) — exists |
| 5 | **8b latency** — PDF criterion 2 and bonus name it | C2 + B1b | 2 | 15 | YES (already planned) | none |
| 6 | **Sample inputs/outputs** — deliverable; nothing exists | deliverable | 1.5 | 10 | YES | one real brief + `data/sample` excerpt |
| 7 | **R3 two-tenant SLA screen** — PDF bonus names multi-tenancy; plan answers with a dimension | B1a + C3 | 2.5 | 20 | ONLY-IF-SWAPPED | `business_unit`, 5 values on every feed — exists |
| 8 | **Task 9 tools + `/api/ask`** — the only evidence the AI is not decoration; a whole solution form; **currently in nobody's lane** | C2 (large), G1 | 5 | 45 (realistically 60) | ONLY-IF-SWAPPED and only if owned at 13:00 | findings + registry — will exist after Tier 1 |
| 9 | **Task 11 `marshal_compliance` + `cost_per_km`** — without them the T&F head's "cost/safety/experience story" is absent | C1 | 3 | 30 | ONLY-IF-SWAPPED (move ahead of 8c/8d) | `actual_escort`, `gender`, `WOMAN_TRAVELLING_ALONE`, `trip_cost`, `total_trip_km` — all exist |
| 10 | **R7 leadership export** — bonus B2 asks for "forward to leadership without rework"; a Slack post is thin | B2 + C1 | 3 | 30 | ONLY-IF-SWAPPED | brief text — will exist |
| 11 | **Task 10 replay controls** — the "watch it sense" beat; proves proactive triggers | G3, C2, demo | 2 | 20 | YES (console lane, already planned) | none |
| 12 | **Task 8c anomaly** — sixth solution form; good-to-have already met with 4–5 | G1 (marginal) | 2 | 30 | ONLY-IF-SWAPPED — demote behind 9, 10, 11 | `alerts.severity`, weekly windows — exist |
| 13 | **8d line-manager view** — persona 3; only ≥1 persona is mandatory; aggregated, not "who" | C1 (marginal) | 2 | 40 (I'd say 50 incl. console) | NO — swap out; keep as reserve | `boarding_status`, `is_no_show`, `actual_pickup_epoch`, `stwid` — exist |
| 14 | **Demo video** — "if requested", zero mentions | deliverable (conditional) | 0–2 | 10 | YES at 16:30 (post-freeze, not a feature) | none |
| 15 | **R4 capacity utilisation** — "ops scale" domain | C1 (marginal) | 1 | 15 | ONLY-IF-SWAPPED (filler) | `actualemployee_cnt`, `actual_cab_capacity` — exist |
| 16 | **R6 driver/cab non-compliance** | C1 (marginal) | 1 | 15 | ONLY-IF-SWAPPED (filler) | `is_driver_nc`, `is_cab_nc` — exist, dtype-drifting |
| 17 | **Task 12 AWS deploy** — makes `PROPOSAL.md` §5 "AWS: yes" true | C3 + preference | 2 | 50 (realistically 75 with CORS/health-check debugging) | NO | none |
| 18 | **R5 alert-ack SLA** | C1 (marginal) | 0.5 | 20 | NO — **and the data undercuts it:** 54 null `acknowledge_time` of 51,699 alerts = 0.1% unacknowledged (`Dictionary/alerts_data.md` L19). A 99.9% metric produces no finding and no story. | exists but uninteresting |
| 19 | **R2 industry benchmark** — fourth reference type | M4 already met | 0.5 | 15 + citation hunt | NO — "cite or omit" resolves to omit: there is no citable published OTA norm for Indian employee-transport ops that a judge could verify | n/a |
| 20 | **R8 counterfactual** | C1 | 1.5 | 45 (plan itself says "most likely to overrun") | NO | vendor volumes — exist |
| — | **"GPS gaps" (PDF good-to-have example)** | — | **0 — not a gap.** No GPS feed exists (`real-dataset-mapping.md` §1). Say it on stage as `PROPOSAL.md` §8.5 plans. **Closed.** | — | — | absent |
| — | **Vernacular feedback / free text** | — | **0 — not a gap.** No comment column (`real-dataset-mapping.md` §3). Correctly cut. **Closed.** | — | — | absent |
| — | **Forecasting** | — | **0 — correctly refused.** Plan L2412–2416. **Closed.** | — | — | — |

One idea not in the reserve that the data supports and the PDF asks for by name: the transport
manager persona "owns vendor coordination, escalations". A **vendor-addressed escalation draft**
from any BREACH finding sliced by `vendor_id` — the same composer, a new `Audience.VENDOR`, a
"Draft escalation" button — turns "act" from *informing* into *acting*. ~20 min after Task 6
exists; worth ~2 points under C1 and C2. Listed here, not costed into the running order.

---

## 4. Swap recommendations

### The arithmetic first

- Window 13:00–16:00 = 180 min × 3 people = **540 person-minutes**.
- Minus the deck lane from 15:00 (`delivery-brief.md` L121: "start by 15:00 at the latest") = **480**.
- Minus realistic Tier 1 slippage (30 min × 3 people — the critical path is 140 sequential
  minutes on one person from 10:05, plus integration) = **~390**.
- Planned Tier 2 = 8 (30) + 8b (15) + 8c (30) + 8d (40) + 9 (45) + 10 (20) + 11 (30) + 12 (50)
  = **260 estimated minutes**. Hackathon estimates run ~1.5× → **~390**.
- Reserve = R1 15 + R2 15 + R3 20 + R4 15 + R5 20 + R6 15 + R7 30 + R8 45 = 175.

**Conclusion: under the plan's own rule ("do not start a reserve item before Tier 2 is done",
`OBJECTIVES.md` L189), no reserve item is ever built.** R1 and R3 — the two that cover things
the PDF names — die on that rule. Swaps are not optional.

### Planned Tier 2 items worth less than a reserve item — swap them

| Swap OUT | Swap IN | Points Δ | Minutes Δ | Risk of the swap |
|---|---|---|---|---|
| **8d line-manager view** (40 min plan, ~50 real; ~2 pts; aggregated so does not actually answer "who") | **R1 EV share (15) + R3 two-tenant SLA screen (20)** | **+2.5** (2 + 2.5 − 2) | **−15 min** | Persona 3 stays "thin" — but M3 needs one persona, `audiences_for` already routes `LINE_MANAGER`, and the honest stage line is "shift-banded findings route to the line manager; the per-employee roll-up is the next sprint". Low risk. |
| **8c anomaly** (30 min; ~2 pts; sixth form when two are required) | **Task 11 `marshal_compliance` + `cost_per_km`** (already planned, demoted to item 7) | **+1** and it fixes the T&F head persona | 0 | 8c is a nicer story; Task 11 is the one whose absence a judge *asks about* ("where's cost?"). Do 8c only if Task 11 is green by 15:00. |
| **Task 12 AWS deploy** (50 min, ~75 real; ~2 pts) | **Architecture diagram (20) + README rewrite (15) + sample I/O (10)** — three PDF deliverables with zero current coverage | **+4.5** | **−30 min** | `PROPOSAL.md` §5 must be edited to stop claiming AWS "Yes" — 2 minutes. S3 + `httpfs` behind `source_for()` remains the *deployability* answer in the diagram. |

### Reserve items to promote unconditionally

- **R1 sustainability / EV share.** PDF §3 lists sustainability as one of the transport manager's
  four accountabilities and PDF §4 lists it among seven data domains; the plan says nothing.
  `actual_cab_fuel_type` exists. One registry entry, 15 min. This is the plan's own "best reserve
  item" (L2359) and the rule that gates it guarantees it never ships. Promote to Tier 2 item 3.
- **R3 two-tenant SLA.** PDF bonus names "multi-tenancy" by name; `PROPOSAL.md` §4 calls the
  in-process engine "a weak multi-tenancy story on its own". `business_unit` has five values on
  every feed. 20 min, and it converts the bonus from a paragraph to a screen. Promote to Tier 2
  item 5, after 8b.

### Reserve items to drop entirely

- **R2 industry benchmark.** M4 is already met with three kinds; the team's own rule is "cite or
  omit" and there is nothing citable a judge can verify. Fifteen minutes of citation hunting for
  half a point and a liability. Drop.
- **R5 alert-ack SLA.** 54 unacknowledged of 51,699 (0.1%). The metric is 99.9% and emits no
  finding. Drop.
- **R8 counterfactual.** 45 min, plan's own "most likely to overrun", projected numbers invite
  the forecasting question the team has rightly refused. Drop.
- Keep **R4** and **R6** as 15-minute fillers for whoever is idle at 15:00 — they exist, but do
  not plan around them.
- **R7 export** stays in reserve but moves to the delivery lane as the first thing after Task 9
  (see below) — it is the cheapest direct answer to bonus B2 and criterion 1's "leadership-ready".

### Revised 13:00–16:00 running order — three lanes, one abort line

Pre-condition (12:30 check): if the 13:00 gate checklist (plan L2008–2017) will not be fully
green by 13:15, **the only Tier 2 items anyone may touch are 8b and R1** (single-file, 15 min
each). Everything else waits for the gate.

| Time | **Lane A — Anshuman (data spine, `service/signaldesk/`)** | **Lane B — Teammate A (console)** | **Lane C — Teammate B (delivery → tools → deliverables → deck)** |
|---|---|---|---|
| 13:00 | Gate. Confirm OTA/OTD target is data-derived (P75 of vendor OTA or trend/peer only), constant carries the measured distribution comment. | `CostMeter` + `BriefPreview` (console-brief Tier 2 #1–2) | **Task 9 tools + `/api/ask`** (45–60). Anshuman grants write to `tools.py`, `model.py` ask-path and one route in `api.py` — say so at 13:00, in the channel, so rule 1 is not violated silently. |
| 13:15 | **Task 8 decomposition** (30) | | |
| 13:45 | **Task 11 — `marshal_compliance`, `cost_per_km`** (30). `experience` only if both land clean. | `ReplayControls` (Task 10, 20) | |
| 14:00 | | `CauseBreakdown` (20) | **R7 leadership export** — markdown of the brief, "Copy for leadership" (30) |
| 14:15 | **R1 EV share** (15) | | |
| 14:20 | | Latency line in cost panel from `/api/cost` (10) | |
| 14:30 | **8b latency meter** (15) — run full sweep on `data/real`, write p50/p95/sweep-seconds into the channel for the deck | `InterrogationPanel` + `ToolTrace` against a fake trace (45) | **Architecture diagram + README rewrite + sample I/O** (45). Diagram = what exists at 14:30 plus the S3/`httpfs` seam. README: prerequisites, `PYTHONPATH=. pytest -q`, run service, run console, env vars. |
| 14:45 | **R3 two-tenant SLA config** (20) — two `business_unit`s, two targets, one sweep | | |
| 15:05 | 8c anomaly **only if** A is green and it is before 15:10; else R4/R6 filler or help B/C | Tenant selector on findings list (15) — makes R3 a screen | **Deck starts** (screenshots come from B) |
| **15:30** | **ABORT LINE.** Anything not green is `git revert`ed, not finished. Allowed after 15:30: demo-path bug fixes, numbers for slides, `git log -p` credential grep, one offline rehearsal (beats 1–6). | **Screenshots of every beat, in order.** | Deck, script, screenshot fallbacks |
| 16:00 | Freeze. Edit `PROPOSAL.md` §5 AWS row to the truth. Push. | | |
| 16:30 | | Record a 3-minute screen capture of the rehearsal (demo video insurance). | |
| 17:00 | Submit. | | |

What this drops relative to the plan: **8d, Task 12, R2, R5, R8**. What it adds: R1, R3, R7,
the three deliverables, and an owner for Task 9. Net planned minutes are roughly equal; net
points are higher because every added item answers something the PDF names.

---

## 5. Three questions a judge will ask that this build cannot currently answer

**Q1. "Where is the AI? Your slide says the model never computes a number, never writes SQL, and
you have a template that ships the brief without it. Why is this 'agentic AI' and not a cron job
with a mail-merge?"**
The team's strongest architectural claim is its weakest under criterion 2's literal wording ("AI
solving a genuine problem rather than decorating"). Today there is no answer because the only
feature where the model *reasons* (Task 9's bounded tool-calling Q&A, refusing a forecast) is
unowned. Cheapest fix before 16:00: (a) land Task 9 and demo beat 8 with the trace visible and
the "what will OTA be next month?" refusal; (b) one slide, ten minutes: *sense = scheduled rules;
reason = verdict engine + tool-mediated Q&A; act = routed dispatch; the model is the interface
and the narrator, and here is why that is the only trustworthy place for it in a system that
touches money and safety.* (c) if there is 20 minutes spare, the vendor-escalation draft (§3
footnote) makes "act" mean more than "post".

**Q2. "Your OTA is 59% against a 90% SLA. Everything is red. Is the dataset broken, is your
five-minute grace wrong, or is every vendor failing — and what SLA does this customer actually
have?"**
`real-dataset-mapping.md` §10b already knows this is coming and offers three options; nothing in
Tier 1's gate checklist verifies which one was taken. Cheapest fix: make "target is data-derived
(P75 of vendor OTA) or absent; constant carries the measured distribution in a comment" a named
line in the 13:00 gate (15 min inside Task 4), and put the delay-minutes distribution on one
slide so the grace choice is shown, not asserted. Say on stage: *"the 90% is the statement's
example, not this customer's contract; we rank against trend and peers because those cannot be
miscalibrated."*

**Q3. "How does this deploy into MoveInSync's platform — Java/Angular, multi-tenant, hundreds
of clients? You are Python plus an in-process database reading a 572 MB CSV on a laptop."**
Currently: an ASCII loop, a paragraph about a repository seam, "AWS: yes" for a deployment that
is last in Tier 2, and a README that says Java and "no code". Cheapest fix (all in Lane C /
Lane A above): the architecture diagram with the two seams labelled (`source_for()` →
local/S3 `httpfs`; registry → DuckDB today / Aurora-Athena adapter tomorrow), the R3 two-tenant
screen, the 8b latency and cost numbers extrapolated to 5k and 50k employees on one slide, and
the honest one-line Java answer `PROPOSAL.md` §5 already has. ~55 minutes total, of which the
diagram and README are deliverables you owe regardless.

---

## Appendix — file:line anchors used above

- PDF §8 mandatory / good-to-have / bonus; §7 six forms; §3 three personas; §4 seven data domains; §9 weights 35/20/20/25; §10 deliverables.
- `PROPOSAL.md` §5 L121–125 (Java/Angular/AWS table), §6 L147 ("Five of six"), §8 L177–201 (known gaps).
- `OBJECTIVES.md` L44–55 (M1–M5), L66 ("Weights from PROPOSAL.md §4"), L97 ("20 free points"), L142–163 (metric tiers), L186–201 (reserve rule), L227–246 (forms).
- Plan L21–33 (schedule), L164–175 (work split, "four people", "Task 9 (AWS)"), L2003–2020 (gate), L2034–2338 (Tier 2), L2340–2410 (RESERVE), L2544–2555 (deliverables), L2563–2565 (template fallback).
- `handoff/README.md` L20–26 (three lanes; Task 9 unowned), L31–33 (rule 1).
- `README.md` L26–33 (stale), `AGENTS.md` L37–39 (stale).
- `data/real/Dictionary/ride_data_trip.md` L24, L34–36; `alerts_data.md` L19, L21; `emp_data.md` L21, L27–31.
- `service/signaldesk/ingest.py` (FEEDS, GLOBS, CRITICAL, UNMATCHED_SQL); `PYTHONPATH=. pytest -q` → 25 passed, 1 skipped.
