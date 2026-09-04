# How three people build this in six hours

**Read this file. Do not read the 1,900-line build plan** —
`docs/superpowers/plans/2026-09-05-signal-desk-python-build.md` is written for
whoever is on the backend critical path and is full of Python you should not
touch. Your brief in this folder is self-contained.

## What we are building, in three sentences

An agent that looks at employee-commute trip data **without being asked**, works
out which metrics have gone wrong relative to a target, their own recent trend,
or their peers, and sends a short brief to the person who can act on it — with
the reasoning and the exact SQL query attached.

The one rule everything rests on: **the model never computes a number.** Rules
decide what is wrong; SQL answers what the figures are; the LLM only turns
settled findings into English. That is why nothing on screen can be a
hallucinated figure.

## Who does what

| Person | Owns | Directory |
|---|---|---|
| **Anshuman** (Claude Code) | The data spine: ingest → metrics → verdict engine → sweep. Deepest, most interdependent, and where every known bug lives. | `service/signaldesk/` |
| **Teammate A** (has a ChatGPT agent) | [`console-brief.md`](console-brief.md) — the whole React console | `console/` |
| **Teammate B** | [`delivery-brief.md`](delivery-brief.md) — Slack + email delivery. **From 13:00: the four tools + `/api/ask`** (Anshuman hands you `tools.py`, the ask-path in `model.py` and one route in `api.py` — he will say so in the channel), then the leadership export, then **by 14:30 at the latest** the architecture diagram, the README rewrite and the sample inputs/outputs, then the deck from 15:05 | `service/signaldesk/delivery.py`, `tools.py`, `docs/`, `deck/` |

The 13:00 hand-off to Teammate B is the one deliberate exception to rule 1 below;
it is said out loud so nobody is editing someone else's file by surprise. Full
running order, by lane and by quarter-hour:
`docs/superpowers/plans/2026-09-05-signal-desk-python-build.md` → "TIER 2".

**Nobody is blocked on anybody.** That is the point of
[`fake-findings.json`](fake-findings.json) — it is exactly what the API returns,
frozen. Build against it and you never need the backend running.

## The four rules that keep three people out of each other's way

1. **Own your directory. Never edit outside it.** Merge conflicts are the
   fastest way to lose an hour today. If you need something changed in someone
   else's directory, message them.
2. **Commit and push every ~30 minutes, and `git pull --rebase` before you
   push.** No pull requests, no review gates — we do not have the hours. Small
   frequent commits on `main`.
3. **`fake-findings.json` is frozen.** If a field name genuinely has to change,
   it is a five-minute conversation with everyone, not a unilateral edit — three
   people are coding against it.
4. **If you are stuck for more than 15 minutes, say so out loud.** Being stuck
   quietly is the single most expensive thing that can happen today.

## The clock

| Time | What |
|---|---|
| 10:00 | Dataset arrives. Anshuman posts the real column headers to the channel immediately. |
| 10:05 | Everyone starts. Do **not** wait for real data — build against `fake-findings.json`. |
| **13:00** | **Everything in your brief marked "Tier 1" must be done.** If it is not, drop everything else and finish it. |
| 13:00–15:00 | Working lunch, keep building. Tier 2 items, in the plan's lane order. |
| 14:30 | Teammate B starts the diagram + README + sample I/O, whatever else is unfinished. |
| 15:05 | Deck starts. Teammate A starts screenshotting every demo beat, in order. |
| **15:30** | **Abort line.** Anything not green is reverted, not finished. After this: demo-path bug fixes, numbers for slides, rehearsal — nothing else. |
| **16:00** | **Feature freeze. No new code.** Deck and rehearsal only. |
| 16:30 | Demo video — Anshuman records it from the frozen build, once the rehearsal and screenshots are done. |
| 17:00 | Submit — this window is worth points on its own. |
| 18:00 | Semifinal, presenting to partner companies. |
| 19:30 | Final jury. |

**16:00 is not negotiable.** An unpolished feature costs a fraction of what a
missing deck costs.

## Using an AI agent on this (ChatGPT, Codex, whatever)

Three things make the difference between an agent that helps and one that
generates plausible rubbish:

- **Paste your brief and `fake-findings.json` into the conversation.** Do not ask
  it to explore the repo. It will read the Python it should not touch, or invent
  field names, and you will spend your afternoon undoing that.
- **Make it write the test first, then the component.** Every brief lists the
  assertions that must exist. An agent asked for "a component and some tests"
  writes tests that pass no matter what the component does — we have a written
  record of that failure mode in `docs/TESTING-LESSONS.md`, where **ten of
  fourteen defects were tests that asserted nothing.**
- **After a test passes, delete the thing it tests and check it fails.** Then put
  it back. This takes thirty seconds and it is the only reliable way to catch a
  test that is asserting nothing. Do it on every test you care about.

Ask it for one component at a time. A request for the whole console at once
comes back as something that compiles and does not work.

## What "done" looks like at 13:00

- The console opens showing a ranked list of findings, worst first
- Clicking a row shows the reference points, the rule that fired, the
  confidence, and the SQL that produced the number
- A brief lands in the real Slack channel, naming a specific vendor and citing
  what it was compared against
- The feed-health panel shows how many rows we could not read

If all four are true we have cleared every mandatory requirement in the problem
statement. Everything after that is upside.
