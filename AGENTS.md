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

## Current state

**No application code. No design spec.** What exists is a proposal.

[`PROPOSAL.md`](PROPOSAL.md) holds the agreed shape: the four-layer
architecture, the mapping to the published scoring weights, the build order with
a protected checkpoint, and a list of genuinely open items. It is awaiting team
sign-off, so treat it as a strong default rather than a settled contract — and
do not start implementing from it without checking that sign-off has happened.

## The one decision to preserve

**The model never computes a number and never writes raw SQL.** Rules decide
what is wrong and who cares; a metric registry answers what the figures are; the
model turns settled findings into language and answers open questions through
validated tools.

If you change anything, do not erode that split. It is what makes the output
trustworthy, the reasoning unit-testable, and the model layer swappable. Several
of the proposal's claims — including its cost-at-scale argument — depend on it.

## Direction

- **Java · Spring Boot** service, **React** console
- Embedded **DuckDB** via the official JDBC driver — no separate database, no
  Redis, no queue
- **Sarvam** as the model layer (`sarvam-105b`; the older Sarvam-M is deprecated
  and no longer served), reached through the official OpenAI Java SDK with a
  base-URL override, since the API is OpenAI-compatible
- Delivery to **Slack** (incoming webhook) and **email** (SES, sandbox, to
  verified addresses)

Anything beyond the above is not yet decided. Do not infer a feature set — check
`PROPOSAL.md`, and prefer asking over assuming.

## Toolchain

Pinned per-project, because this machine hosts other projects on older
runtimes and their defaults must not change.

**Node — pinned to 22 via `.nvmrc`.** The global default is deliberately still
18 for other work. Run `nvm use` on entering the repo. Vite 7 requires Node
20.19+ or 22.12+, so 18 fails outright rather than degrading. Two guards
enforce this: `.npmrc` sets `engine-strict=true` (gates `npm install`), and
`scripts/require-node.mjs` gates `npm run dev` — wire it as the frontend's
`predev` script, since `engine-strict` does nothing for `run`.

**Java — use JDK 21 LTS at `/opt/homebrew/opt/openjdk@21`.** It is keg-only, so
it shadows nothing. This matters: Homebrew's `maven` pulls **JDK 26** as a
dependency and Maven will use it by default, ahead of the JDK 22 on `PATH`.
Lombok and Spring plugins routinely break on a JDK that new, and the failure is
cryptic. Set `JAVA_HOME` before building:

```sh
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
mvn -v   # confirm it reports 21, not 26
```

**DuckDB — CLI 1.5.5 installed, matching the JDBC driver.** The `httpfs`
extension is already cached in `~/.duckdb/extensions/`, so an S3 read will not
try to download it mid-demo.

## Secrets

The Sarvam API key and the Slack webhook URL live in environment variables and
must never reach a commit, a screenshot, or the deck. A Slack webhook URL is a
credential in its own right: anyone holding it can post to the channel. If you
add configuration, add it to `.env.example` with placeholder values.

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
