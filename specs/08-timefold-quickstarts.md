# 08 — Timefold Quickstarts

**Reuse: 🟡 MEDIUM-HIGH — the pattern, plus one policy you're missing.**
`github.com/TimefoldAI/timefold-quickstarts` · Java/Quarkus · ⭐575 ·
Apache-2.0 · updated 2026-09-02 · **38.6 MB → 6.4 MB sparse**

Cloned sparse: `use-cases/vehicle-routing` + `use-cases/employee-scheduling`.
(15 use-cases available — `git sparse-checkout set use-cases/<name>` for more.)

## 1. Why a Java repo is in your reference set

Timefold (the OptaPlanner successor) is a **constraint-based** solver: you don't
write an algorithm, you declare named constraints and the solver searches. Its
`ConstraintProvider` classes are the closest published analogue to the
commute-os policy engine — same shape, production-hardened, and each constraint
carries a **human-readable name** used in reporting.

That last detail is the whole design of your `PolicyTrace`. Independent
convergence on the pattern is worth knowing.

## 2. `EmployeeSchedulingConstraintProvider.java` — the eight constraints

```
:56  Missing required skill
:64  Overlapping shift
:77  At least 10 hours between 2 shifts
:84  Max one shift per day
:93  Unavailable employee
:102 Undesired day for employee
:111 Desired day for employee
:121 Balance employee shift assignments      ← ★ you don't have this
```

Note the split: hard constraints (skill, overlap, rest) versus soft preferences
(desired/undesired days). The commute-os policy engine already has this as
`block` / `warn` / `pass`. Same idea, and again arrived at independently.

## 3. The policy you're missing: **fairness**

`"Balance employee shift assignments"` uses a load-balancing collector to spread
assignments evenly rather than optimally-but-unfairly.

**Apply it to pooling and it's a real, unexploited insight.** Every merge
imposes a detour on someone. Optimise pure cost and the same unlucky employee in
the far corner of Bellandur absorbs the detour *every single day*. That is how
a pooling programme loses employee trust and quietly dies — which is a much
more plausible failure mode for MoveInSync than a suboptimal route.

Add as a tenth policy:

```ts
// core/policies/detour-fairness.ts
// PURPOSE: stop the same employee absorbing the detour every day.
// PIVOT: if the statement is about adoption/experience, promote this to hero.
export const detourFairness: Policy = (c, w, ctx) => {
  const worst = Math.max(...Object.entries(c.perPassengerAddedMin)
    .map(([id, min]) => min + (ctx.detourMinutesThisWeek[id] ?? 0)))
  return worst > FAIR_WEEKLY_DETOUR_MIN
    ? { id: 'detour-fairness', name: 'Detour fairness', status: 'warn',
        slack: { value: FAIR_WEEKLY_DETOUR_MIN - worst, unit: 'min/week' },
        reason: `Employee has absorbed ${worst} min of detour this week` }
    : { id: 'detour-fairness', name: 'Detour fairness', status: 'pass',
        reason: 'Detour load evenly distributed' }
}
```

Requires one field: `PolicyCtx.detourMinutesThisWeek: Record<string, number>`.

**Why this wins points.** Every team will optimise cost. A system that says
*"this merge is cheapest, but Priya has taken the detour four days running, so
we're proposing the second-best merge instead"* demonstrates you understand that
commute programmes fail on **employee trust**, not arithmetic. It's the kind of
observation that comes from thinking about operations rather than algorithms.

## 4. `VehicleRoutingConstraintProvider.java` — four constraints

```
:41  VEHICLE_CAPACITY
:49  SERVICE_FINISHED_AFTER_MAX_END_TIME
:60  MAXIMIZE_VISITS_ASSIGNED
:71  MINIMIZE_TRAVEL_TIME
```

Note `MAXIMIZE_VISITS_ASSIGNED` ranks **above** `MINIMIZE_TRAVEL_TIME`. Serving
people matters more than short routes. Make sure `scenario.ts` doesn't
accidentally reward dropping trips to look efficient — an easy way to produce an
impressive-looking demo that a sharp judge takes apart in one question.

## 5. Also relevant if the statement shifts

`use-cases/` holds 15 quickstarts. Two are worth knowing about:

- **`facility-location`** — if the statement is about depot or charging-hub
  placement
- **`flight-crew-scheduling`** — duty-time and rest-period modelling, more
  rigorous than a 12-hour cap, if driver compliance becomes the theme

## 6. What to ignore

All of it, as code. Java 17 + Quarkus + Maven; nothing ports to Next.js. Read
the two `ConstraintProvider` files — about 130 lines each and genuinely
readable even if you don't write Java.

## 7. Verdict

Twenty minutes of reading for **one new policy** (`detour-fairness`) and one
correction (never reward dropping trips). The fairness policy is the single
best idea recovered from any repo in this set that wasn't already in the design.
