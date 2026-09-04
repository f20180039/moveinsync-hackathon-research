# Signal Desk — build proposal

An agent that watches enterprise commute operations, works out what a transport
manager needs to know before they ask, and sends it — with the reasoning attached.

| | |
|---|---|
| Statement | Agentic Intelligence & Reporting Layer for Enterprise Mobility |
| Theme | Agentic AI (Enterprise Mobility / Operations Intelligence) |
| Timebox | ~14 hours |
| Stack | Java · Spring Boot · React |
| Data | Embedded DuckDB (JDBC), no backing services |
| Model | Sarvam-105B (free credits from the organisers) |
| Status | **Proposal — awaiting team sign-off. No code written yet.** |

---

## 1. What changed

We prepared against a guess: a cab-pooling and route-optimisation engine. The
statement that arrived is a different problem. It asks for an **agentic
intelligence and reporting layer** over mobility operations data, and the
mandatory bar explicitly rules out *"a passive dashboard or query-only tool"*.

So the solver work — savings heuristics, corridor indexing, pickup ordering — is
not the product. It is archived at the git tag `prep/pooling-prototype` and
recoverable, but it is not coming with us.

What survives is one pattern worth more than the code it came from: a
**four-tier verdict engine** that scores something, names the cause, and records
its reasoning. That becomes the part of this build the model does *not* do.

---

## 2. The product, in one loop

A transport manager's day goes into assembling data rather than acting on it.
The pain named in the statement is sharper than that: *a metric without context
is just a number.* "OTA is 78%" means little; "it was 85% last month, SLA is
90%, and two vendors own the gap" is a decision.

Signal Desk runs that second sentence on its own, unprompted, delivers it to the
person who can act, and then defends its answer if challenged.

---

## 3. Architecture

```
LAYER 1 — INGEST                    schema-tolerant, loud about what it can't read
  ├─ Trip logs .......... cab / nodal / shuttle CSV; mismatched columns merged
  │                       read_csv_auto(union_by_name = true)
  ├─ Quarantine ......... unparseable rows + reason, so bad data is a visible
  │                       number, not silent loss   store_rejects -> reject_errors
  ├─ Gap register ....... GPS holes, unmatched vendor records, roster gaps
  │                       counted per feed as a confidence figure
  └─ Vernacular feedback  employee feedback in mixed languages, normalised for
                          scoring, original kept verbatim   [Sarvam Mayura]
                                    |
                                    v
LAYER 2 — METRIC REGISTRY           the governed vocabulary; nothing queries raw tables
  ├─ Metric definitions   on-time arrival, SLA breach rate, cost per trip,
  │                       vendor on-time share, night-trip compliance
  ├─ Reference points ... each metric declares what it is judged against:
  │                       own trend | SLA target | peer comparison
  └─ Slice dimensions ... vendor, site, shift, mode, route (enumerated, validated)
                                    |
                                    v
LAYER 3 — THE AGENT LOOP
  SENSE  ->  REASON  ->  COMPOSE  ->  ACT
    |          |           |            |
    |          |           |            └─ delivers by severity, logs what it
    |          |           |               sent, to whom, on what evidence
    |          |           └─ Sarvam-105B writes the brief over findings already
    |          |              computed — prose only, never arithmetic   [MODEL]
    |          └─ rules compare each metric to its reference points, emit ranked
    |             findings: severity, cause, audience   (four-tier verdict engine)
    └─ fires on a clock tick or fresh upload — no human prompt
                                    |
                                    v
LAYER 4 — SURFACES                  two personas, one artifact
  ├─ Manager console .... findings ranked by severity, expandable to the numbers
  │                       and the rule that fired
  ├─ Interrogation panel  "why is this vendor flagged?" answered through the same
  │                       registry, exposed as model tools   [MODEL]
  └─ Leadership brief ... the sent artifact: a dated summary a facilities head can
                          forward upward without editing it first
```

Everything is deterministic and unit-testable except the two blocks marked
`[MODEL]`, which produce language only.

### The one architectural decision that matters

**The model never computes a number and never writes raw SQL.** Rules decide
what is wrong and who cares; the registry answers what the figures are; Sarvam
turns settled findings into language and handles open-ended questions through
validated tools.

That split buys three things at once: nothing on screen can be a hallucinated
figure, the reasoning is unit-testable, and prompts stay small because the model
sees aggregates rather than rows — which is the cost story the rubric asks for
by name.

It also makes the model layer swappable, which turned out to matter. We are
running on Sarvam rather than a frontier model, and because the arithmetic never
passes through it, that changes the prose and nothing else. A weaker model
narrating settled findings is safe; a stronger model computing figures would not
be.

---

## 4. Why this scores

| Criterion | Weight | How this build answers it |
|---|---:|---|
| Business impact & experience | 35 | The manager stops assembling and starts deciding. Output is addressed to a named persona and is forwardable as-is — which also takes the bonus. |
| Functionality | 25 | End to end on the provided dataset, with a real delivery at the end of the loop rather than a mocked one. |
| Agentic design & cost at scale | 20 | The loop starts without a prompt. Aggregation happens in DuckDB, so tokens per interaction stay flat as row counts grow. One model call per brief, not one per row — which is why a 60 req/min tier is ample. |
| Architecture & code quality | 20 | One stateless Spring Boot service, no backing stores, clean seams between registry, rules and model — and it drops into a Java platform without a rewrite, which is what "deployable into an existing platform" is asking. |

We combine **four** of the six solution forms — proactive alerting, automated
narrative, conversational agent, decision-support console — against a
good-to-have that asks for two.

---

## 5. Build order

Sequenced so the demo exists early and only widens.

| # | Item | Est. |
|---|---|---|
| 1 | Synthetic dataset with **planted faults** — GPS gaps, unmatched records, roster holes injected deliberately, so the agent has something real to find and swapping in the provided file is a config change | ~1.5 h |
| 2 | Ingest and quarantine — CSV into embedded DuckDB, rejected rows surfaced with reasons | ~1 h |
| 3 | Metric registry, **three metrics only**, each with its reference point. Adding a fourth later costs minutes; getting the shape wrong costs the day | ~2 h |
| 4 | Verdict engine and findings — rules, severity tiers, cause, audience. Unit-tested, no model involved | ~2 h |
| **5** | **VERTICAL SLICE COMPLETE — STOP AND DEMO IT.** One trigger, one rule, one composed brief, one real Slack message. Every remaining item is additive: if we run out of time we still have a working agentic demo rather than four unfinished halves | **~7 h elapsed** |
| 6 | Compose and dispatch — Sarvam writes the brief; Slack webhook and SES to verified addresses | ~1.5 h |
| 7 | Manager console — ranked findings, expandable to evidence and the rule that fired | ~2.5 h |
| 8 | Interrogation panel — registry as model tools. *First thing cut if time runs short* | ~1.5 h |
| 9 | Vernacular feedback — multilingual employee feedback into an experience metric. *Droppable, but highest payoff per hour: the one thing a GPT/Claude competitor cannot easily copy* | ~1 h |
| 10 | Deck, architecture diagram, README, demo drill (one rehearsal offline in case the venue network fails). **Non-negotiable — these are scored deliverables** | ~1.5 h |

---

## 6. Do these tonight

**These three cannot wait until hour zero.**

1. **Create the Slack incoming webhook.** Minutes, no approval. This is our
   primary delivery channel.

2. **Verify 2–3 team email addresses in AWS SES.** SES in sandbox delivers only
   to *verified* addresses. Leaving sandbox now requires SPF, DKIM and DMARC
   records in place *before* the request can be filed, and approval runs 4–24 h
   for established domains and 1–3 business days for new ones — so
   **production SES is not achievable by tomorrow.** Slack is the primary
   channel; SES-to-verified-addresses is the real email proof. Both are genuine
   delivery.

3. **Fire one real Sarvam call with a tool in it.** Not a hello-world. Send a
   request to `sarvam-105b` declaring a `tools` array and confirm the response
   returns `finish_reason: "tool_calls"`. **Tool calling is the one capability
   the interrogation panel cannot be built without** — the difference between
   learning that tonight and learning it at hour ten is the whole feature. While
   there, note the credit balance and confirm the key authenticates over
   `Authorization: Bearer`, since that is the path the OpenAI Java SDK takes.

---

## 7. Settled decisions

- **Personas** — transport manager operates it; the transport & facilities head
  receives the brief. Two of the three personas covered by one artifact.
- **Real delivery, not drafts** — the agent genuinely sends, chosen over an
  approval queue for demo impact, with the SES constraint handled by channel
  choice.
- **Java + Spring Boot, React console** — Java is the platform's own language,
  which converts criterion 3's "deployable into an existing platform" from an
  argument we have to make into a fact. The cost-at-scale story never depended
  on the runtime; it comes from calling the model once per brief instead of once
  per row.
- **Sarvam as the model layer** — free credits, and the API is OpenAI-compatible
  with real tool calling, so the official OpenAI Java SDK works against it with
  a base-URL override. Use `sarvam-105b`; **the older Sarvam-M is deprecated and
  no longer served.** Its Indic language stack is a genuine advantage for this
  domain, not a consolation.
- **Embedded DuckDB, no backing services** — official JDBC driver from DuckDB
  Labs (MIT, Maven Central) with platform natives bundled in the jar, so no
  cross-compilation step and no database to stand up.

---

## 8. PENDING — needs a decision or an owner

**These are the open items. Nothing below has been decided.**

- [ ] **Approve the shape.** Does *rules decide, model narrates* hold as the
      core split? This is the load-bearing decision — everything else follows
      from it.
- [ ] **Approve the hour-seven vertical slice** as the checkpoint we protect
      above all else.
- [ ] **React for the console — any objection?** Java is settled. Nothing in the
      rubric asks for Angular, but say so if you want full stack alignment.
- [ ] **Which three metrics ship first.** Proposed: on-time arrival, SLA breach
      rate, vendor on-time share. If the provided dataset is thin on any of
      them we swap *before* writing rules, not after. **Needs an owner.**
- [ ] **Who owns the deck.** It is a scored deliverable and it always ends up
      written at 3am by whoever is least busy. **Name someone now.**
- [ ] **Who holds the API keys.** The Sarvam key and the Slack webhook URL both
      live in environment variables, with only an `.env.example` in the repo.
      **A Slack webhook URL is a credential** — anyone holding it can post to
      the channel — so it must not reach a commit, a screenshot, or the deck.

### Live risk

- [ ] **The provided dataset is still unseen.** We design against synthetic data
      built to the described shape and keep ingestion schema-tolerant. If the
      real file diverges badly, the cost lands in the registry's metric
      definitions — which is exactly why they stay declarative and few. Whoever
      gets the dataset first should post the column headers immediately.

---

## Notes

No implementation has started and the design spec is not yet written — the
sequencing is deliberate, since it is far cheaper to overturn the shape now than
after a spec argues from it.

Every dependency, model ID and timing above was verified against upstream
documentation rather than recalled, which caught three stale facts worth knowing:
the community DuckDB Go driver was archived and handed to the DuckDB team,
Sarvam-M was deprecated in favour of the 105B models, and SES sandbox now
demands DNS records before a production request can even be filed.
