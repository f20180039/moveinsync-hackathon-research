# 08 — Timefold Quickstarts · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/TimefoldAI/timefold-quickstarts` |
| **Reuse** | 🟡 **MEDIUM-HIGH** — the scoring architecture, plus one policy you lack |
| **Stack** | Java 17 · Quarkus/Spring · Maven · Timefold Solver (OptaPlanner successor) |
| **Size** | **38.6 MB → 6.4 MB sparse** · ⭐575 · Apache-2.0 · updated 2026-09-02 |
| **Local** | `reference/timefold-quickstarts/` (sparse: 2 of 15 use-cases) |

```sh
git sparse-checkout set use-cases/vehicle-routing use-cases/employee-scheduling
```

15 use-cases available: `bed-allocation`, `conference-scheduling`,
`employee-scheduling`, `facility-location`, `flight-crew-scheduling`,
`food-packaging`, `maintenance-scheduling`, `meeting-scheduling`,
`order-picking`, `project-job-scheduling`, `school-timetabling`,
`sports-league-scheduling`, `task-assigning`, `tournament-scheduling`,
`vehicle-routing`.

---

## 1. Why a Java repo is in your reference set

Timefold is **constraint-based**: you don't write a search algorithm, you declare
named constraints and the solver searches. A `ConstraintProvider` returns an
array of `Constraint` objects, each built from a stream, given a penalty weight,
and **named with a human-readable string** used in score explanation.

That is the commute-os policy engine, arrived at independently by a commercial
OR vendor — including the detail that each rule carries a display name for
reporting, which is the entire design of `PolicyTrace`.

Two files are worth your time. Both are ~125 lines and readable without knowing
Java.

---

## 2. `VehicleRoutingConstraintProvider.java` — three-tier scoring

```java
public static final String VEHICLE_CAPACITY = "vehicleCapacity";
public static final String MAXIMIZE_VISITS_ASSIGNED = "maximizeVisitsAssigned";
public static final String SERVICE_FINISHED_AFTER_MAX_END_TIME = "serviceFinishedAfterMaxEndTime";
public static final String MINIMIZE_TRAVEL_TIME = "minimizeTravelTime";

return new Constraint[] {
    // Hard constraints
    vehicleCapacity(factory),
    serviceFinishedAfterMaxEndTime(factory),
    // Medium constraints
    maximizeVisitsAssigned(factory),
    // Soft constraints
    minimizeTravelTime(factory)
};
```

### 2.1 The finding: `HardMediumSoftScore` — **three** tiers

The score is lexicographic: any hard violation dominates all medium, which
dominates all soft. So the priority order is absolute, not a weighted trade-off:

| Tier | Constraint | Meaning |
|---|---|---|
| **Hard** | capacity, service-past-max-end-time | never acceptable |
| **Medium** | maximize visits assigned | **serve everyone** before optimising |
| **Soft** | minimize travel time | then be efficient |

**The commute-os policy engine has two effective tiers** — `block` and
`warn`/`pass`. It's missing the middle one, and the middle one is what
structurally prevents the failure mode where dropping a trip looks like an
efficiency win.

Recommended change to `PolicyStatus`:

```ts
type PolicyStatus = 'pass' | 'soft' | 'medium' | 'block'
//  block  = hard   : gender-safety, seat-capacity, driver-hours, ev-range
//  medium = serve everyone : unassigned trips (spec 06 §5)
//  soft   = optimise : detour-fairness, zone-confidence, cost
```

`scenario.ts` then compares plans lexicographically by tier rather than summing
into one number — so no amount of kilometre saving can ever outrank leaving an
employee behind.

**FleetPy reaches the same conclusion by a different route** — every objective
subtracts a large `assignment_reward` per served request (spec 07 §5). Two
independent systems enforcing "serve everyone first" makes this a rule, not a
preference.

### 2.2 Penalties are weighted by violation magnitude

```java
.penalize(HardMediumSoftScore.ONE_HARD,
          vehicle -> vehicle.getTotalDemand() - vehicle.getCapacity())
```

Not a flat penalty — the amount by which the constraint is broken. Over by two
seats is twice as bad as over by one.

The commute-os `PolicyVerdict.slack` already carries this magnitude, but nothing
consumes it: a blocked proposal is simply discarded. Feed `slack` into a score
and you get near-miss ranking for free — which is what makes the admin-override
idea (spec 05 §5) coherent.

### 2.3 `forEachIncludingUnassigned`

```java
factory.forEachIncludingUnassigned(Visit.class).filter(v -> v.getVehicle() == null)
```

A separate stream method, because the default `forEach` skips unassigned
entities. Unassigned work is invisible unless you deliberately look for it — a
useful warning for the `unassigned[]` handling in spec 06 §5.

---

## 3. The policy you're missing: fairness

`EmployeeSchedulingConstraintProvider.java:121`

```java
Constraint balanceEmployeeShiftAssignments(ConstraintFactory f) {
    return f.forEach(Shift.class)
            .groupBy(Shift::getEmployee, ConstraintCollectors.count())
            .complement(Employee.class, e -> 0L)   // include employees with NO shifts
            .groupBy(ConstraintCollectors.loadBalance(
                        (employee, shiftCount) -> employee,
                        (employee, shiftCount) -> shiftCount))
            .penalizeBigDecimal(HardSoftBigDecimalScore.ONE_SOFT, LoadBalance::unfairness)
            .asConstraint("Balance employee shift assignments");
}
```

### 3.1 Why it matters for pooling

Every merge imposes a detour on somebody. Optimise pure cost and the same
unlucky employee in the far corner of Bellandur absorbs the detour **every
single day** — because the geometry that made them expensive yesterday is
unchanged today. The optimiser is not being unfair by accident; it is being
*consistently* unfair by construction.

That is how a corporate pooling programme actually dies: not from bad
arithmetic, but from the twenty people who quietly start booking their own cabs.
It's a far more plausible failure mode for MoveInSync than a suboptimal route,
and it is invisible to every cost-only optimiser.

### 3.2 The `.complement()` detail — don't miss this

`.complement(Employee.class, e -> 0L)` injects employees with **zero**
assignments into the stream before balancing. Without it, fairness is measured
only across employees who already got something, and the ones getting nothing
are invisible to the fairness metric.

The direct analogue: measure detour load across **all** employees, including
those who have never been pooled. Otherwise "fair" means "fair among the
already-burdened."

### 3.3 Implementation

```ts
// core/policies/detour-fairness.ts
/**
 * PURPOSE: stop the same employee absorbing the pooling detour every day.
 * PIVOT: if the statement is about adoption / employee experience, promote to hero.
 * SAFE-TO-DELETE: no — this is the differentiating policy.
 */
const FAIR_WEEKLY_DETOUR_MIN = 90

export const detourFairness: Policy = (c, w, ctx) => {
  // include every employee, not just those in this candidate (the .complement() lesson)
  const worst = Math.max(...c.trips.flatMap(t => t.employeeIds).map(id =>
    (ctx.detourMinutesThisWeek[id] ?? 0) + (c.perPassengerAddedMin[id] ?? 0)))

  const over = worst - FAIR_WEEKLY_DETOUR_MIN
  return over > 0
    ? { id: 'detour-fairness', name: 'Detour fairness', status: 'soft',
        slack: { value: -over, unit: 'min/week' },
        reason: `${worst} min of detour absorbed this week — ${over} over the fair share` }
    : { id: 'detour-fairness', name: 'Detour fairness', status: 'pass',
        slack: { value: -over, unit: 'min/week' },
        reason: 'Detour load evenly distributed' }
}
```

Requires one new field: `PolicyCtx.detourMinutesThisWeek: Record<string, number>`
(seeded from fixtures — make it deliberately lumpy so the policy fires on stage).

### 3.4 The demo beat

> *"This merge is the cheapest available. But Priya has absorbed 84 minutes of
> detour this week — she's taken the hit four days running. So we're proposing
> the second-best merge instead: ₹40 less saving, and the detour moves to
> someone who hasn't carried it. Cost-only optimisers can't see this, and it's
> the reason pooling programmes lose employees."*

That reads as operational understanding rather than algorithmic cleverness,
which is the harder thing to fake and the rarer thing to see.

---

## 4. The other seven employee-scheduling constraints

| Line | Constraint | Tier | Relevance |
|---|---|---|---|
| `:56` | Missing required skill | hard | same mechanism as VROOM `skills` (spec 06 §3) |
| `:64` | Overlapping shift | hard | penalty = **minutes of overlap** |
| `:77` | At least 10 hours between 2 shifts | hard | **driver rest** — see below |
| `:84` | Max one shift per day | hard | — |
| `:93` | Unavailable employee | hard | employee on leave → no trip to schedule |
| `:102` | Undesired day for employee | soft | preference, penalised |
| `:111` | Desired day for employee | soft | **`.reward(...)`, not penalise** |
| `:121` | Balance shift assignments | soft | §3 |

Three notes:

**`atLeast10HoursBetweenTwoShifts`** computes its penalty as
`(10 * 60) - breakLength` — minutes *short* of the required rest. This is the
right shape for driver rest between duties, and it's stricter than the
commute-os 12-hour cumulative cap: a driver can be under 12 hours total and
still have had insufficient rest since their last duty. Combine with VROOM's
`breaks` (spec 06 §4) for a genuinely defensible compliance story.

**`desiredDayForEmployee` uses `.reward(...)`.** Constraints can be positive.
The commute-os engine only ever penalises — there's no way to express "this
merge is *preferable* because both employees are on the same floor and already
carpool socially." Adding a `'bonus'` status is cheap and makes suggestion
ranking richer than pure cost.

**Joiner DSL.** `forEachUniquePair(Shift.class, equal(Shift::getEmployee),
overlapping(Shift::getStart, Shift::getEnd))` — declarative pair matching with
`equal` / `overlapping` / `lessThanOrEqual` joiners. Conceptually this is
candidate generation: "all unique pairs sharing an office and overlapping in
time." Worth mirroring as a small helper so `pool-merger`'s grouping reads
declaratively rather than as nested loops.

---

## 5. Domain classes — worth a glance

```
vehicle-routing/domain/     Location, LocationAware, LocationDistanceMeter,
                            Vehicle, Visit, VehicleRoutePlan, geo/, dto/
employee-scheduling/domain/ Employee, Shift, EmployeeSchedule
```

Note `LocationAware` and `LocationDistanceMeter` are separate from `Location` —
"has a position" and "can measure between positions" are distinct interfaces.
Small thing, but it's why their distance strategy is swappable, and it's the
same separation as the design's `RouteProvider` interface.

`Visit` vs `Vehicle` is the demand/supply split again — the third repo in this
set to model it that way (see spec 01 §3).

---

## 6. Other use-cases worth knowing about

If the problem statement shifts, two more are one `sparse-checkout` away:

- **`facility-location`** — depot or charging-hub placement. Relevant if the
  statement is about infrastructure siting rather than daily routing.
- **`flight-crew-scheduling`** — duty-time, rest-period and qualification
  modelling far more rigorous than a 12-hour cap. The reference to raid if
  driver compliance becomes the theme.

---

## 7. What to ignore

All of it, as code. Java 17 + Quarkus + Maven; nothing ports to Next.js, and
Timefold's solver is a runtime dependency you cannot embed. Read the two
`ConstraintProvider` files, take the architecture, close the repo.

---

## 8. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | **Add `detour-fairness` as policy #10** | `core/policies/detour-fairness.ts` | 1 h |
| 2 | **Three-tier status** `pass`/`soft`/`medium`/`block` | `core/policy.ts` | 45 min |
| 3 | Lexicographic plan comparison by tier | `core/scenario.ts` | 45 min |
| 4 | Weight penalties by `slack` magnitude | `core/policy.ts` | 30 min |
| 5 | Include never-pooled employees in fairness | `policies/detour-fairness.ts` | 15 min |
| 6 | Add a `'bonus'` verdict for preferable merges | `core/policy.ts` | 30 min |
| 7 | Driver rest-since-last-duty, not just daily total | `policies/driver-hours.ts` | 30 min |
| 8 | Declarative pair-joiner helper for grouping | `solvers/pool-merger.ts` | 30 min |

Item 1 is the single best idea recovered from any repo in this reference set
that wasn't already in the design. Items 2–3 are the structural fix that stops
your own demo from being gameable.
