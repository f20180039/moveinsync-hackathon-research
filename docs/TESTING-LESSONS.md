# Test Integrity — what 11 tasks of TDD actually taught us

**Written 2026-09-03**, from executing an 11-task TDD plan end to end (191 tests,
43 commits, every diff reviewed). That project was cleared from this repo when
the real problem statement turned out to be a different problem — see
[`AGENTS.md`](../AGENTS.md) — but the findings below are about how tests fail as
tests, not about that domain, so they carry over unchanged.

Read this for one habit above all: **after a test passes, delete the behaviour it
is named for and confirm it fails.** That single step caught ten tests that were
asserting nothing.

Across eleven tasks, ~173 tests and a full review of every diff, the score was:

| | count |
|---|---|
| Defects in implementer code | **0** |
| Defects in the plan/spec I wrote | **14** |
| — of which **vacuous tests** | **10** |
| — of which **real logic bugs** | **3** |
| — of which impossible expectations | **1** |

Every single finding was in something the *planner* wrote, not the *implementer*.
The implementers transcribed faithfully, added nothing, and reported every
discrepancy instead of reconciling it. That ratio is the headline: **when the
plan contains the code, the risk moves entirely into the plan.**

---

## The vacuous-test pattern, in three escalating kinds

A vacuous test passes even when the behaviour it is named for is deleted. Ten
appeared. They are not all the same problem, and only the first kind is fixable
by "asserting harder".

### Kind 1 — the assertion is too weak (fixable by care)

The test asserts a single case under a name that claims a general property.

- `'still flags a real Date.now() call'` — passed under an identity function
- `'does not silently swap lat and lng'` — asserted `toBeLessThan(10)` on a pair
  3.6 km apart; a **reversed** coordinate adapter returns 3.74 km, still under 10
- `'scales carbon linearly with distance'` — one data point, so the function
  could have been a hardcoded lookup

**Rule:** a test name that claims a general property ("scales", "never", "always",
"is optimal") needs **two or more data points**, or it may only claim the single
point it actually asserts.

### Kind 2 — the test has no subject (NOT fixable by care)

The behaviour under test was erased by a structural choice, so no assertion
strength would have helped.

- `'travels the reverse direction too'` — the graph was built **undirected**, so
  traversal worked from a single forward edge. The test passed with reverse-edge
  synthesis *deleted*.
- `'never emits a zero-km edge'` — the guard it tested was **unreachable**: every
  zero-distance row was also a terminal row already skipped by an earlier guard.
  It also passed against an empty edge list, since `[].filter(...)` is `[]`.

**Rule:** you cannot reason your way to these. Only deleting the behaviour and
watching the test survive finds them.

### Kind 3 — the vacuous test conceals a live bug (the dangerous kind)

- `time-window` blocked only when a pickup was *after all* windows and warned
  only when *before all*. A pickup in a **gap between two windows** was neither,
  so it fell through to `pass()`. An employee offering "07:00–07:10 or
  08:00–08:30" would have had 07:30 approved.

The masking path and the bug were the *same code path*. The test could not fail,
and the reason it could not fail was the defect.

---

## The protocol that found them: break-it-to-prove-it

After the suite is green, for each test that claims to prove a behaviour:

1. **Delete or invert the behaviour** it names.
2. **Confirm that test fails.**
3. **Restore, confirm green.**
4. **Report the result** — a surviving check matters more than a green suite.

Cost: a few minutes per task. Return across this run: **10 vacuous tests, 3 real
logic bugs, 1 impossible expectation.** Of those, the four found *only* by this
step would have shipped otherwise — including a safety-policy hole.

**A check that survives is the finding.** In Task 8/9, replacing a multiplicative
probability with a naive sum passed all four tests, because every fixture put
both formulas on the same side of the threshold. The implementation was correct
and faithful; the *test selection* was the defect. Nothing else in the process —
not the tests, not a full review — would have caught it.

---

## Six habits that actually paid, in order of value

1. **Break-it-to-prove-it on every guard.** See above. Highest return by far.
2. **"Report the discrepancy, never reconcile."** Standing instruction to every
   implementer: if a stated count or expected value does not match reality,
   transcribe verbatim and *report* — never add, delete or adjust a test to make
   a number match. It caught **four** wrong counts and one impossible
   expectation. The stated numbers themselves caught nothing.
3. **Verify the reviewer's claims yourself before acting.** Twice a review's
   framing was right but its severity or reasoning needed checking; once a
   verification script of mine printed a conclusion its own data contradicted.
   Derive verdicts from data; never print them beside the evidence.
4. **State invariants in the plan, not just in the file.** `slack` was
   "remaining headroom" in three policies and "cost incurred" in a fourth,
   returning **negative slack on a passing verdict**. Writing the invariant into
   the plan's global constraints — before six more policies were written — is
   what stopped it spreading.
5. **Per-item verdicts when batching.** Two tasks were batched to save dispatch
   cycles, with the review required to verdict **each policy by name**. Six came
   back approved and two changes-requested — including a safety bug. An
   aggregate verdict would have averaged that into "approved with minor notes".
6. **Ambiguous prose in a spec becomes a bug in code.** Three defects traced to
   my own wording. `gender-safety` counted day-leg passengers as chaperones
   because §7 said "merged group" instead of "night-flagged trips". The
   implementer transcribed the design faithfully; the design was wrong.

---

## The fourth kind: defects invisible to any per-task review

Eleven tasks passed individual review. The final whole-branch review then found
two **critical, demo-visible** defects — and neither was catchable earlier,
because every task was individually correct against its own contract. The
contradiction only existed *between* modules.

### Both were "correct code, wrong when combined with real data"

**1. Occupancy read 89.29% in a product whose premise is that cabs run
half-empty.** `computeMetrics` accumulated seats once per distinct *vehicle* but
passengers once per *trip*. The fixture generator round-robins 40 vehicles over
200 trips, so each vehicle carries five sequential dispatches and the metric
treated them as one simultaneous load — a 5× inflation. Neither module was
wrong. The metrics task never saw the generator's round-robin; the generator
task never ran the metrics.

**2. The fleet beat its own theoretical floor** — 40 vehicles against a
"no routing can beat this" bound of 50. `vehiclesUsed` counted vehicle *assets*;
the floor counted *dispatches*. Two units on one KPI row. Each was internally
consistent.

**3. Night-shift trips ran at 10:30 in the morning.** The fixture day was
anchored in UTC; `isNightShift` is documented as 21:00–06:00 *local*. In IST the
flag inverted in both directions — flagged-night trips at 10:30, unflagged
logouts at 23:51. No policy recomputed night-ness from a timestamp, so nothing
in the test suite could notice.

### Why the process missed them, precisely

Every one of these lived in the gap between two green tasks. And the most telling
detail: **the occupancy invariant was already written down as a test** — it
asserted `floor < vehiclesUsed` against a synthetic 8-trip world. The rule was
known. It was simply never pointed at the data that ships.

### The lesson, and it is cheap

> **Assert your headline invariants against the real fixtures, not a synthetic
> fixture, and do it in the same suite.**

Two tests, added at the end, would have caught all three:

```ts
// the floor is a LOWER bound — it cannot exceed what was achieved
expect(m.theoreticalFloorVehicles).toBeLessThanOrEqual(m.vehiclesUsed)
expect(m.avgOccupancyPct).toBeLessThan(60)      // the premise is half-empty cabs

// the night flag must agree with LOCAL time, in both directions
for (const t of trips) expect(istHour(t) >= 21 || istHour(t) < 6).toBe(t.isNightShift)
```

A synthetic-world test proves a function's arithmetic. A real-fixture test proves
the *product* is coherent. Both are needed, and only the second catches a
cross-module contradiction.

### A corollary about deferring

Two findings I had filed as *future* obligations turned out to be *present*
defects, and the final reviewer said so:

- I recorded the hard-coded 4-seat fleet-floor unit as a problem for later, when
  12-seat shuttles arrive. The floor already exceeded usage — with cabs, today.
- I recorded an unknown-status ranking gap as a JSON-boundary concern for the UI
  plan. It already meant one returned object could carry `blocked: true`
  alongside `tier: 'pass'`.

Deferring is a legitimate tool and most of the deferrals held up under scrutiny.
But "this bites once feature X arrives" deserves one check: *does it bite now?*
Both of these did, and both were cheap to fix at the point of discovery.

## Applying this on hackathon day

Under time pressure the instinct is to skip the break-it step. Don't — it is
the cheapest of these habits and by far the highest-yield.

The minimum viable version, when there is no time for the full protocol:

- For each **blocking** rule (safety, capacity, compliance), delete it and
  confirm a test goes red. If none does, that refusal is decorative.
- For any golden threshold, **measure it first, then pin it** at ~80% of the
  measured value with the number in a comment. A threshold nobody measured
  either asserts nothing or invites lowering the bar to match.
- Never let a demo number come from a test you have not seen fail.
