# AGENTS.md — orientation for an AI agent working in this repo

Read this first if you're picking up this repo cold.

## Current state

The repo has just been cleared of prep work built against a guessed problem
statement. The real problem statement has now arrived and is a different
problem, so that prep was removed. There is no application code here yet, and
no design spec for the new problem — the repo is awaiting that work.

## What this repo is now for

Building an **Agentic Intelligence & Reporting Layer for Enterprise
Mobility** — an agentic system for reporting and intelligence over mobility
operations data. The tech direction is **Go + React on AWS**.

No product design, architecture, or feature set has been written down yet.
Do not infer or invent one — wait for the design spec, or for explicit
direction, before assuming any specifics beyond what's stated here.

## What was removed, and where it went

Earlier prep explored a vehicle-pooling/routing optimiser (a TypeScript
prototype called `commute-os`, specs analysing eight cloned VRP/pooling
reference repos, and the design docs and plans built on top of that). All of
it is preserved at the annotated tag `prep/pooling-prototype`, which points at
the commit just before the cleanup. Nothing is destroyed — it's just not on
this branch's working tree. Recover a path from it with:

```sh
git show prep/pooling-prototype:<path>
git checkout prep/pooling-prototype -- <path>
```

## What's kept

- [`docs/TESTING-LESSONS.md`](docs/TESTING-LESSONS.md) — the one document from
  the prior prep judged transferable regardless of problem domain.
- `.superpowers/` — agent workspace, git-ignored, not part of the repo's
  tracked content.

## Conventions

None established yet for the new build. Follow whatever standards land with
the design spec and initial scaffolding.
