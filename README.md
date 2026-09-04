# Signal Desk

Build workspace for the MoveInSync hackathon: an **Agentic Intelligence &
Reporting Layer for Enterprise Mobility**.

An agent that watches enterprise commute operations, works out what a transport
manager needs to know before they ask, and sends it — with the reasoning
attached.

## Start here

| Document | What it is |
|---|---|
| [`docs/superpowers/plans/2026-09-05-signal-desk-python-build.md`](docs/superpowers/plans/2026-09-05-signal-desk-python-build.md) | **The plan you execute on build day.** Tiered against the real ~6-hour schedule. Start here. |
| [`docs/superpowers/specs/2026-09-04-signal-desk-design.md`](docs/superpowers/specs/2026-09-04-signal-desk-design.md) | The design spec, v1.1. **Read §15 first** — it supersedes the body's stack and deployment. |
| [`PROPOSAL.md`](PROPOSAL.md) | The original argument. Read it for the *reasoning*, not the stack or the budget — it assumes ~14 hours and a Java backend, and both changed. |
| [`docs/MoveInSync-problem-statement.pdf`](docs/MoveInSync-problem-statement.pdf) | The problem statement as issued by the organisers. The authority — every design decision answers to it. |
| [`docs/TESTING-LESSONS.md`](docs/TESTING-LESSONS.md) | How to keep tests honest under time pressure. Domain-independent. |
| [`AGENTS.md`](AGENTS.md) | Orientation for an agent or a person picking this repo up cold. |

## Status

**No application code yet, and no design spec.** The proposal is deliberately
ahead of the spec: it is far cheaper to overturn the shape now than after a spec
argues from it.

Direction so far: **Java · Spring Boot · React**, embedded **DuckDB** over the
provided trip-log dataset, **Sarvam** as the model layer, delivering to Slack
and email. The reasoning is deterministic and testable; the model writes
language only. `PROPOSAL.md` explains why.

## The prep that was cleared

This repo previously held preparation built against a *guess* at the problem
statement — a vehicle-pooling and route-optimisation engine. The real statement
turned out to be a different problem, so that work was removed rather than left
around to mislead.

Nothing was destroyed. The annotated tag `prep/pooling-prototype` points at the
commit where it all still lives:

```sh
git show prep/pooling-prototype:<path>          # inspect a file
git checkout prep/pooling-prototype -- <path>   # bring one back
```

Worth a look from that tag if you ever want it: `commute-os/src/core/policy.ts`,
a four-tier verdict engine whose pattern *is* carried forward into this build.

## Secrets

Nothing credential-shaped belongs in this repo. The Sarvam API key and the Slack
webhook URL live in environment variables only — a Slack webhook URL is itself a
credential, since anyone holding it can post to the channel.
