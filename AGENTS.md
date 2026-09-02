# AGENTS.md — orientation for an AI agent working in this repo

Read this first. It tells you what this repo is, what it deliberately does not
contain, and how to get the missing context in one command.

## What this repo is

Research and design prep for the **MoveInSync / Bessemer Tech Catalyst mobility
hackathon** (Bengaluru, ~2026-09-05). The problem statement was not known in
advance, so the work is deliberately problem-agnostic.

It contains **no application code**. It is:

1. `specs/` — detailed technical specs of 8 open-source routing/pooling repos
   (~2,480 lines), with `file:line` citations, algorithm walkthroughs, bugs
   found, and costed action lists.
2. `docs/superpowers/specs/2026-09-02-commute-os-design.md` — the design for
   `commute-os`: a problem-agnostic core (world model, policy engine,
   cost/carbon ledger, scenario harness) plus two solvers, **Pool Merger**
   (Clarke-Wright savings) and **Metro Feeder Mesh**.

## What it does NOT contain, and why

The 8 analysed repos are **not vendored here**. Three of them declare no licence
at all, so redistributing their source is not ours to do. The specs cite them by
`file:line`, so you need the clones only to follow a citation.

## Get the missing context

```sh
./scripts/setup-reference.sh              # all 8 into reference/  (~29 MB)
./scripts/setup-reference.sh pyvrp vroom  # or just the ones you need
```

Idempotent — existing directories are skipped. `reference/` is git-ignored and
must stay that way.

`reference-repos.json` is the machine-readable manifest: for each repo a `url`,
`clone` strategy (`full` | `sparse`), `sparse_paths`, `licence`, `reuse` rating,
the `spec` that analyses it, a `why`, and a `read_first` list of the files that
actually matter. Parse that rather than scraping the README. It also has a
`rejected` array recording two repos that were checked and found empty, so you
don't re-investigate them.

## Reading order

| Order | File | Why |
|---|---|---|
| 1 | `specs/INDEX.md` | Router. Verdict table, "do these five things", and **"Answers to have ready"** for judge questions. Has a spec-depth table so you open only what you need. |
| 2 | `docs/superpowers/specs/2026-09-02-commute-os-design.md` | The design being built toward. §18 has the build order and an explicit cut line. |
| 3 | `specs/04`, `specs/06`, `specs/01` | The three highest-value specs, in that order. |

Do **not** read all 8 specs unless asked. They total ~98 KB and `INDEX.md`
exists to route you.

## Conventions if you contribute

- **Verify before asserting.** Three of the five originally-supplied repos were
  mis-sold in the source brief; that was found by `grep` and file listing, not by
  reading READMEs. Every claim in `specs/` is traceable to a file and line — keep
  it that way, and mark anything unverified as an assumption.
- **Cite `file:line`** for any claim about a reference repo.
- Keep `reference/` git-ignored. Never commit third-party source.
- The design spec's §17 lists assumptions still needing verification. If you
  verify or retire one, update §17 rather than leaving it stale.
- Spec numbering (`01`–`08`) is stable and referenced across files. Don't
  renumber.

## Known state

- `reference/` upstream links are **detached** on the 3 inactive clones
  (`Car-Pooling-System`, `RideShare-Optimizer`,
  `smart-aiport-cabpooling-backend`); the 5 actively-maintained ones keep `.git`
  and can be refreshed with `git pull`.
- `commute-os` itself is **not yet implemented** — the design is approved, the
  implementation plan was not written. Eleven-plus design changes from the repo
  research are tabulated in `specs/INDEX.md` and should be folded into the design
  spec before planning.
