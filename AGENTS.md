# AGENTS.md — orientation for an agent working in this repo

Read this before doing anything else here.

## What this repo is

The build workspace for a MoveInSync hackathon entry answering the statement
**"Agentic Intelligence & Reporting Layer for Enterprise Mobility"**.

The problem statement is committed at
[`docs/MoveInSync-problem-statement.pdf`](docs/MoveInSync-problem-statement.pdf)
and is **the authority**. Read it before proposing anything. Its mandatory bar
matters: the solution must sense, reason and act — a passive dashboard or a
query-only tool is explicitly ruled out.

## Current state (last updated 2026-09-04, evening)

**Read these two, in this order, before anything else:**

1. [`docs/superpowers/specs/2026-09-04-signal-desk-design.md`](docs/superpowers/specs/2026-09-04-signal-desk-design.md)
   — the design spec, **v1.1. Read §15 (Amendment 1.1) FIRST**; it supersedes the
   body's Java signatures and its Render/Vercel deployment.
2. [`docs/superpowers/plans/2026-09-05-signal-desk-python-build.md`](docs/superpowers/plans/2026-09-05-signal-desk-python-build.md)
   — **the plan you execute.** Tiered against the real ~6-hour schedule.

`PROPOSAL.md` is the original argument and is now partly stale: it assumes ~14
hours and a Java backend. Read it for the *reasoning* (why an embedded database,
why the model narrates rather than computes), not for the stack or the budget.

The 24-task Java plan at `docs/superpowers/plans/2026-09-04-signal-desk-build.md`
is **superseded. Do not execute it.** It is worth reading only for the eight
resolved spec ambiguities and the bug list, both of which the Python plan carries
forward.

**What exists as code:** nothing yet. **What exists as data:** the committed
fixture at `data/fixture/` — six feeds, 177,072 rows, seven planted faults, and
one vendor degrading over the final three weeks. That last one is the demo.

## The one decision to preserve

**The model never computes a number and never writes raw SQL.** Rules decide
what is wrong and who cares; a metric registry answers what the figures are; the
model turns settled findings into language and answers open questions through
validated tools.

If you change anything, do not erode that split. It is what makes the output
trustworthy, the reasoning unit-testable, and the model layer swappable. Several
of the proposal's claims — including its cost-at-scale argument — depend on it.

## Direction

- **Python 3.12 · FastAPI · uvicorn** service, **React 19 · Vite 7** console
- Embedded **DuckDB** via the `duckdb` package — no separate database, no Redis,
  no queue
- **Sarvam** as the model layer (`sarvam-105b`; Sarvam-M is deprecated and no
  longer served), reached through the official **OpenAI Python SDK** with a
  `base_url` override, since the API is OpenAI-compatible
- Delivery to **Slack** (incoming webhook) and **email** (SES, sandbox, to
  verified addresses)
- Infrastructure on **AWS** (~$100 of credits): S3 for the trip logs, read
  directly by DuckDB's `httpfs`; App Runner or Lambda for the service;
  S3 + CloudFront for the console

**The backend was Java + Spring Boot until 2026-09-04 evening.** It is retired to
the annotated tag `prep/java-spring-prototype` and removed from the tree so nobody
spends part of a six-hour build day reading the wrong backend.

Anything beyond the above is not yet decided. Check the plan, and prefer asking
over assuming.

## Toolchain

Pinned per-project, because this machine hosts other projects on older
runtimes and their defaults must not change.

**Python — 3.12, one virtualenv at `service/.venv`**, dependencies pinned in
`service/requirements.txt`. No Poetry, no Conda: a packaging argument at 10:30
costs more than it saves.

**Node — pinned to 22 via `.nvmrc`.** The global default is deliberately still
18 for other work. Run `nvm use` on entering the repo. Vite 7 requires Node
20.19+ or 22.12+, so 18 fails outright rather than degrading. Two guards
enforce this: `.npmrc` sets `engine-strict=true` (gates `npm install`), and
`scripts/require-node.mjs` gates `npm run dev` — wire it as the frontend's
`predev` script, since `engine-strict` does nothing for `run`.

**Java is no longer needed** for the build. It is only needed to regenerate the
fixture, which you should not do — see below. If you ever do: JDK 21 LTS at
`/opt/homebrew/opt/openjdk@21`, keg-only, and note that Homebrew's `maven` pulls
JDK 26 and prefers it over whatever is on `PATH`, which breaks Lombok and Spring
plugins with a cryptic failure.

**DuckDB — CLI 1.5.5 installed.** The Python package is `duckdb`. The `httpfs`
extension is cached in `~/.duckdb/extensions/`, so an S3 read will not try to
download it mid-demo. Note for the record: **`duckdb_jdbc:1.5.5` does not exist
on Maven Central** — the newest published coordinate is `1.5.5.1`, whose driver
matches the CLI. Irrelevant now, but it cost time once.

## Secrets

The Sarvam API key and the Slack webhook URL live in environment variables and
must never reach a commit, a screenshot, or the deck. A Slack webhook URL is a
credential in its own right: anyone holding it can post to the channel. If you
add configuration, add it to `.env.example` with placeholder values.

## The fixture — do not regenerate it

`data/fixture/*.csv` is committed: six feeds, 177,072 rows, 7.6 MB, deterministic
output of a seeded generator. It carries all seven planted faults the spec
requires (measured: malformed 1.36%, unclosed trips 2.29%, unmatched costs 2.78%,
unmatched feedback 2.79%, non-English comments 40.55%, gapped GPS 11.44%, orphan
roster 4.75%) and the planted three-week regression in vendor **V07** that the
whole demo narrative is built on.

The generator that produced it is Java and lives at the tag
`prep/java-spring-prototype`. **Do not port it.** The real dataset arrives at
10:00 on build day and replaces this as a config change; the generator's only
remaining job would be regenerating a fixture nobody needs to regenerate.

## The prep that was cleared

Earlier work in this repo targeted a *guess* at the problem statement — a
vehicle-pooling and route-optimisation engine (a TypeScript prototype called
`commute-os`, specs for eight cloned VRP reference repos, and the plans built on
them). The real statement is a different problem, so that work was removed to
stop it misleading anyone.

It is preserved in full at the annotated tag `prep/pooling-prototype`:

```sh
git show prep/pooling-prototype:<path>
git checkout prep/pooling-prototype -- <path>
```

**Do not resurrect it wholesale.** Almost none of it applies. The exception is
the pattern in `commute-os/src/core/policy.ts` — a four-tier verdict engine
carrying cause, severity and a reasoning trace — which is the ancestor of this
build's rules layer and is worth reading once.

## What's kept

- [`docs/TESTING-LESSONS.md`](docs/TESTING-LESSONS.md) — the taxonomy of vacuous
  tests and the break-it-to-prove-it protocol. Written during the prep, but
  domain-independent, and the single most useful habit to carry into a timed
  build: after a test passes, delete the behaviour it is named for and confirm
  it fails.
- `.superpowers/` — agent scratch workspace, git-ignored, not tracked content.
