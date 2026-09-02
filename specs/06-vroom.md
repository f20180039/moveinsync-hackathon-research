# 06 — VROOM · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/VROOM-Project/vroom` |
| **Reuse** | 🟢 **HIGH** — highest value-per-minute document in the reference set |
| **Stack** | C++17 · CMake · pluggable routing (OSRM / Openrouteservice / Valhalla) |
| **Size** | 1.8 MB · ⭐1849 · BSD-2-Clause · © Julien Coupey 2015-2025 |
| **Read** | `docs/API.md` — **481 lines, read it end to end** |
| **Local** | `reference/vroom/` |

You will not compile or run VROOM. Its value is that `docs/API.md` is a
**ten-year-old, production-hardened schema for the exact problem commute-os
models** — and it answers three design questions better than the current spec.

---

## 1. Two solving modes — and the second one is the demo

**Default VRP mode.** Input a problem, get routes satisfying all constraints.
Standard.

**Plan mode (`-c`).** Input a problem *plus the route you intend to run*.
Then, quoting `API.md:31-37`:

> All constraints in input implicitly become **soft** constraints. The output is
> a set of routes matching the expected description while minimizing timing
> violations and **reporting all constraint violations**.

**This is exactly the commute-os demo beat.** Design §12 says "blocked
proposals are shown, not hidden" — an admin needs to see *why* a merge is
refused and by how much it misses. VROOM has a dedicated mode for that, because
real dispatchers need it.

The architectural lesson: **evaluating a proposed plan and generating an optimal
plan are two different operations**, and the evaluator must return structured
violations rather than a boolean. The commute-os `evaluate()` → `PolicyTrace`
function *is* plan mode. Build it as a first-class entry point, not a filter
inside the solver.

---

## 2. The `violation` object — your `PolicyVerdict`, production-named

`API.md:437-441`:

```
violation: { cause: string, duration?: integer }
```

Where `duration` is "earliness (resp. lateness) if cause is `lead_time`
(resp. `delay`)" — i.e. **the magnitude of the miss**, which is precisely the
commute-os `slack` field.

The ten canonical causes (`API.md:445-455`), mapped:

| VROOM cause | commute-os policy | Notes |
|---|---|---|
| `delay` | `detour-sla` | late against a time-window end |
| `lead_time` | `time-window` | early against a window start — **you're missing this one** |
| `load` | `seat-capacity` | vehicle over capacity |
| `max_tasks` | — | cap on stops per route; a cheap extra guard |
| `skills` | `gender-safety`, `gate-spread` | see §3 |
| `precedence` | — | pickup without its delivery |
| `missing_break` | `driver-hours` | see §4 |
| `max_travel_time` | `driver-hours` | duty-time ceiling |
| `max_distance` | `ev-range` | distance ceiling |
| `max_load` | — | load cap *during a break* |

Two gaps worth closing:

- **`lead_time`** — arriving *too early* is a violation too. A merged pickup
  that collects someone 25 minutes before their window opens is a real SLA
  failure your current `time-window` policy (overlap within 15 min) doesn't
  catch. Add it as a `warn`.
- **`max_tasks`** — a cap on pickups per route. Independent of seats: four
  passengers at four separate doorsteps is a much worse experience than four at
  two doorsteps, even though `seat-capacity` passes both.

Adopt the `cause` string vocabulary verbatim. Free credibility, and it makes the
`PolicyTrace` legible to anyone who has worked with routing tools.

---

## 3. `skills` — one mechanism instead of N special cases

`API.md:379-392`:

> Job skills are **mandatory**, i.e. a job can only be served by a vehicle that
> has **all** its required skills. In other words: job `j` is eligible to
> vehicle `v` iff `j.skills` is included in `v.skills`.
>
> - a task without skills can be served by any vehicle;
> - a vehicle without skills can only serve tasks with no particular need.

A subset test. That's the whole rule.

Several commute-os policies are special cases of it:

| Policy | As skills |
|---|---|
| `gender-safety` | night trip with a lone female requires `FEMALE_SAFE_ESCORT`; only qualifying vehicles offer it |
| `ev-range` | a long merged route requires `LONG_RANGE`; EVs don't offer it |
| `gate-spread` | a Gate-5 drop requires `GATE_5_ACCESS` |
| accessibility | requires `WHEELCHAIR` |

**Keep the policy engine.** Skills give a boolean; they cannot say *"blocked,
and you were 3 minutes short."* The traces and slack values are the demo's whole
point. But implement the *check* inside those policies as a skill-set subset
test, so rule ten becomes an enum member rather than a new code path.

Note the deliberate asymmetry in their default: **no skills on a task means
anyone can serve it; no skills on a vehicle means it can serve only
unconstrained tasks.** That default fails safe — an unconfigured vehicle can't
accidentally pick up a passenger with a safety requirement. Copy that polarity.

---

## 4. `breaks` — driver compliance done properly

`API.md:143-151`:

```
break: { id, time_windows[], service, description, max_load[] }
```

The commute-os `driver-hours` policy is one cumulative 12-hour ceiling. Real
compliance is a **scheduled obligation**: the break has its own time windows,
its own duration, and (via `max_load`) can be forbidden while passengers are
aboard.

That last field is the subtle one. `max_load` on a break means *"this driver
cannot take their mandated break while carrying four employees."* So a merge
that fills the cab across the driver's break window is non-compliant even
though total duty time is fine. A pure cumulative cap cannot express that.

Concrete upgrade to `Driver`:

```ts
type Driver = {
  id: string; name: string
  dutyMinutesToday: number
  score: number
  breaks: { dueBy: number; takenAt?: number; minutes: number }[]   // NEW
}
```

Then `driver-hours` returns `warn` when a merge pushes a break past `dueBy`, and
`block` when the cumulative cap is exceeded. Two failure modes, one policy,
correctly separated.

---

## 5. `priority` — handling over-subscription honestly

`API.md:71` and `:399-404`: integer `[0, 100]`, and

> Useful in situations where **not all tasks can be performed**, to gain some
> control on which tasks are unassigned.

VROOM treats over-subscription as the normal case. The output has a top-level
`unassigned` array (`API.md:352`) and the summary reports `unassigned` count and
total `priority` sum.

**The commute-os design has no concept of an unserved trip** — it assumes
infinite cabs. That's a soft spot a sharp judge will find: at 07:45 in Bellandur
you are always short.

Adding it creates a *better* demo moment, not a worse one: *"at peak we're 12
cabs short. Here's who we serve first — night-shift and airport runs outrank a
flexible 10 am login — and here's who slips to the next wave."* Admitting a real
constraint and handling it deliberately beats implying it doesn't exist.

Changes: add `priority: number` to `Trip`, `unassigned: Trip[]` to
`SolverResult`, and `unassignedCount` to `Metrics`.

---

## 6. Schema details worth copying wholesale

### 6.1 `shipment` — the right shape for an employee trip

`API.md:78-99`. A `shipment` is a **paired pickup + delivery that must ride the
same vehicle**, with a precedence constraint between them.

That is exactly an employee trip. The commute-os `Trip` carries loose
`pickupAt` / `officeId` / `gateId` fields with the pairing implicit. Modelling
it as an explicit pickup step and delivery step, each with its own
`time_windows` and `service` duration, is cleaner — and it gives you the
`precedence` violation for free.

### 6.2 `time_windows` is an **array**

`API.md:73`, and `:418-426`. Not one window — several. Real employees have
"07:00–07:30 **or** 08:15–08:45" (two shuttle waves), not a single interval.

The design's single `windowStart` / `windowEnd` pair cannot express that. Change
to `windows: [number, number][]`. The overlap test becomes "any window of A
intersects any window of B" — a few extra lines, materially more realistic.

Also note their semantics: arrival before a window start incurs **waiting
time**, and service may legitimately extend past the window end. Only the
*start* must fall inside. That's a meaningful precision your `time-window`
policy should match.

### 6.3 `costs` per vehicle

`API.md:130-135`:

```
cost: { fixed, per_hour (default 3600), per_task_hour, per_km }
```

Cost lives on the **vehicle**, not globally. `ledger.MODEL` is currently one
flat object; splitting it per vehicle type is what lets an EV, a CNG sedan and a
12-seat shuttle have genuinely different economics — which the Metro Feeder
solver needs, since it compares a cab against a shuttle.

Note `per_hour` defaults to 3600 (one cost unit per second) — time is the
default objective and distance is opt-in. Worth remembering when someone asks
what you're actually optimising.

### 6.4 `setup` vs `service`

`API.md:406-411`. `setup` is the cost of *arriving somewhere new* and is **not
re-applied** for another task at the same location; `service` is per-task.

Directly relevant: two employees at the same apartment gate cost
`setup + 2×service`, not `2×(setup + service)`. Same-building colleagues are
cheaper to pool than the design currently models — which makes pooling look
*better*, so it's worth getting right.

### 6.5 `speed_factor`, `max_travel_time`, `max_distance`

Per-vehicle scaling and ceilings (`API.md:123-127`). `speed_factor` is the clean
way to implement the design's `trafficMultiplier` slider — per vehicle rather
than globally, so you can model a shuttle being slower than a sedan.

### 6.6 `matrices` per profile

`API.md:306-340`. Custom duration/distance/cost matrices keyed by vehicle
profile:

```json
"matrices": { "car":  { "durations": [[0,14],[21,0]] },
              "bike": { "durations": [[0,57],[43,0]] } }
```

**This is `routes.cache.json`, and it validates the design's central risk
decision.** Supplying matrices makes coordinates optional and eliminates every
routing-engine call. VROOM — a production tool — supports fully offline
operation as a first-class input mode. Precomputing the cache isn't a hackathon
shortcut; it's how the real thing is deployed.

---

## 7. Output format → model `/api/solve` on this

`API.md:341-435`. Top level:

```
{ code, error?, summary, unassigned[], routes[] }
```

- `code`: `0` ok · `1` internal · `2` input · `3` routing. Four codes, not HTTP
  status soup.
- `summary`: `cost, routes, unassigned, setup, service, duration, waiting_time,
  priority, violations[], delivery[], pickup[], distance`
- `route`: `vehicle, steps[], cost, setup, service, duration, waiting_time,
  priority, violations[], geometry (polyline), distance`
- `step`: `type (start|job|pickup|delivery|break|end), arrival, duration, setup,
  service, waiting_time, violations[], location, id, load[], distance`

Three things to lift:

1. **`waiting_time` as a reported metric.** Time an employee spends waiting
   because the cab arrived early. Pooling *creates* waiting time — a good
   dashboard shows it rather than hiding it.
2. **`load[]` after each step.** Occupancy is per-step, not per-trip. This is
   what lets `MapCanvas` show a badge changing `1/4 → 2/4 → 4/4` as the cab
   moves — a far better animation than a static badge.
3. **`geometry` as an encoded polyline** on the route object. Matches
   `Proposal.geometry` in the design; keep the polyline encoded in transit and
   decode in the client.

---

## 8. What to ignore

The entire C++ implementation (`src/`), CMake build, OSRM/ORS/Valhalla
adapters, CLI plumbing. Read `docs/API.md`, skim `docs/example_1.json` +
`example_1_sol.json` (routing-engine mode) and `example_2.json` (custom-matrix
mode), and stop.

`example_3.json` is the interesting one: it demonstrates plan mode `-c` with an
over-capacity route and with lead-time/delay violations — i.e. a worked example
of the exact "show me why this is blocked" output you're building.

---

## 9. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | Adopt the 10 `violation.cause` strings verbatim | `core/policy.ts` | 15 min |
| 2 | Add `lead_time` (too-early pickup) as a `warn` | `policies/time-window.ts` | 15 min |
| 3 | `windows: [number,number][]` instead of one pair | `core/types.ts` | 30 min |
| 4 | Suitability checks as skill subset tests | `core/policies/*` | 45 min |
| 5 | `breaks[]` on `Driver` incl. `max_load` semantics | `policies/driver-hours.ts` | 30 min |
| 6 | `priority` + `unassigned[]` for over-subscription | `scenario.ts`, `solver.ts` | 45 min |
| 7 | Move `costs` from global ledger onto vehicle type | `core/ledger.ts` | 30 min |
| 8 | `setup` vs `service` split (same-gate discount) | `core/scenario.ts` | 20 min |
| 9 | Report `waiting_time`; `load[]` per step | `Metrics`, `MapCanvas` | 30 min |
| 10 | `evaluate()` as a first-class entry point, not a filter | `core/policy.ts` | design |

≈ 4½ hours, and it takes the data model from "hackathon plausible" to "looks
like it has met production."
