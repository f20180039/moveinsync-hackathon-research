# 05 — PyVRP · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/PyVRP/PyVRP` |
| **Reuse** | 🟢 **HIGH** — for its constraint vocabulary, which validates our design |
| **Stack** | Python API over a C++17 core (pybind11) · numpy · `vrplib` |
| **Size** | 3.6 MB · ⭐685 · **MIT** · updated 2026-08-31 |
| **Paper** | arXiv:2403.13795 — *"PyVRP: a high-performance VRP solver package"* |
| **Local** | `reference/pyvrp/` |

Algorithm: **Hybrid Genetic Search** (HGS) — population-based crossover plus
Iterated Local Search, with adaptive penalties for infeasibility.

**You will not run this in the demo** (see §7). Its value is threefold: it names
the constraints you're modelling, it hands you two portable metrics, and it
gives you a citation.

---

## 1. Layout

```
pyvrp/
├─ Model.py                  ★★★ the modelling API — read this one file
├─ _pyvrp.pyi                type stubs for the C++ core (ProblemData, Solution,
│                            Route, Client, Depot, VehicleType, CostEvaluator)
├─ solve.py                  solve() + SolveParams
├─ IteratedLocalSearch.py    the ILS driver
├─ PenaltyManager.py         ★ adaptive infeasibility penalties (§5)
├─ minimise_fleet.py         ★★ fleet minimisation + a bin-packing bound (§4)
├─ Result.py                 cost / is_feasible / summary
├─ Statistics.py             per-iteration telemetry, CSV-dumpable
├─ read.py                   VRPLIB + Solomon instance parsing
├─ stop/                     FirstFeasible, MaxIterations, MaxRuntime,
│                            NoImprovement, MultipleCriteria
├─ search/ + cpp/search/     local-search operators (§6)
├─ plotting/                 10 plot helpers (§8)
└─ cpp/                      C++ core: Client, Depot, VehicleType, Route,
                             CostEvaluator, DurationSegment, LoadSegment…
```

---

## 2. `Model.add_client()` — `Model.py:237`

```python
def add_client(
    self,
    location: Location,
    delivery: int | list[int] = [],
    pickup: int | list[int] = [],
    service_duration: int = 0,
    tw_early: int = 0,
    tw_late: int = np.iinfo(np.int64).max,
    release_time: int = 0,
    prize: int = 0,
    required: bool = True,
    group: ClientGroup | None = None,
    *, name: str = "",
) -> Client
```

Fields worth mapping onto `Trip`:

| Field | Meaning | commute-os |
|---|---|---|
| `delivery` / `pickup` | **vector** quantities | `seatsUsed` → make it a vector (§3) |
| `service_duration` | dwell at the stop | boarding time — the design ignores this; 60–90 s per pickup is real and adds up over four stops |
| `tw_early` / `tw_late` | time window | `windowStart` / `windowEnd` |
| `release_time` | earliest the task may *start being served* | shift-release time — when an employee actually clocks off |
| `prize` | value gained by serving | see `required` below |
| `required` | must this be served? | **the design assumes always true** |
| `group` | mutually exclusive client group | `gender-safety` (§3) |

**`required=False` + `prize` is prize-collecting VRP.** An optional client is
served only if its prize exceeds the routing cost. That's the principled version
of VROOM's `priority` (spec 06 §5): instead of ranking who gets dropped, you
attach a *value* to serving them and let the objective decide. For commute-os,
`prize` maps naturally onto shift criticality — a night-shift pickup has a high
prize because failing it has real consequence.

---

## 3. `Model.add_vehicle_type()` — `Model.py:428`

The finding that matters. Parameters, with the commute-os policy each
corresponds to:

| PyVRP parameter | Default | commute-os policy / ledger field |
|---|---|---|
| `num_available` | 1 | fleet size |
| `capacity` | `[]` | **`seat-capacity`** — note: a *vector* |
| `start_depot` / `end_depot` | None | `Depot` |
| `fixed_cost` | 0 | `ledger.cabBaseFarePerTrip` |
| `tw_early` / `tw_late` | 0 / max | driver working window |
| `shift_duration` | max | **`driver-hours`** (the 12 h cap) |
| `max_distance` | max | **`ev-range`** |
| `unit_distance_cost` | 1 | `ledger.cabRatePerKm` |
| `unit_duration_cost` | 0 | `ledger.driverCostPerHour` |
| `profile` | None | EV vs ICE road behaviour |
| `start_late` | None | latest permissible departure |
| `initial_load` | `[]` | passengers already aboard |
| `reload_depots` / `max_reloads` | `[]` / MAX | multi-trip vehicles — **a shuttle doing two waves** |
| `max_overtime` / `unit_overtime_cost` | 0 / 0 | driver overtime, priced |

**Nine of the commute-os policies have a direct counterpart here.** They were
derived independently from the PRD's edge cases; a mature OR solver exposes the
same constraints under established names. That's independent confirmation the
model is right — and it gives you the vocabulary to *say* so.

Three specific upgrades fall out:

**3.1 Vector capacity.** `capacity: int | list[int]`, and `API` note "put the
most important/limiting metrics first". For employee transport:

```ts
capacity = [seats, luggage, wheelchairSlots]
```

The `seat-capacity` policy currently checks one scalar. Vectorising it costs
almost nothing and handles accessibility — an angle nearly nobody at a mobility
hackathon will cover, and one an enterprise buyer with accessibility
obligations will immediately recognise.

**3.2 `ClientGroup` for gender safety.** `Model.py:347`:

```python
def add_client_group(self, required: bool = True, *, name: str = "") -> ClientGroup
```

A *mutually exclusive* group: at most one member may be served. The docstring at
`:237` notes it raises "when a required client is being added to a mutually
exclusive client group" — so exclusivity is enforced at model-build time, not
discovered mid-search. That's the right shape for a hard safety rule: make the
illegal combination unrepresentable rather than filtered.

**3.3 `reload_depots` / `max_reloads` — multi-wave shuttles.** A vehicle may
return to a depot and reload. That is exactly a feeder shuttle running two
waves between metro station and office, which Metro Feeder Mesh needs and the
current design cannot express (it assumes one route per vehicle).

---

## 4. `minimise_fleet.py` — two things to steal

### 4.1 The objective

```python
def minimise_fleet(data, stop, seed=0, params=SolveParams()) -> VehicleType
```

Not "shortest routes" but **"what is the fewest vehicles that admits a feasible
solution?"** The loop (`:60-75`) is a linear descent: drop one vehicle, re-solve
with `MultipleCriteria([FirstFeasible(), stop])`, repeat while
`num_available > lower_bound`.

Note the stopping criterion — `FirstFeasible` means it stops as soon as *any*
feasible solution exists, because at this stage feasibility is the question and
optimality is irrelevant. Good pattern.

For an enterprise commute buyer this *is* the question. Not "we saved 8.2 km"
but **"the same 200 employees move with 138 cabs instead of 174."** Cabs are the
cost line; kilometres are a proxy. The design already has `vehiclesUsed` in
`Metrics` — lead the KPI strip with it.

Restrictions worth knowing (`:52-58`): raises on multiple vehicle types, and on
optional clients.

### 4.2 `_lower_bound()` — a free third number for your dashboard

```python
def _lower_bound(data: ProblemData) -> int:
    bound = 0
    for dim in range(data.num_load_dimensions):
        demand = max(sum(c.delivery[dim] ...), sum(c.pickup[dim] ...))
        capacity = vehicle_type.capacity[dim] * vehicle_type.max_trips
        bound = max(int(np.ceil(demand / max(capacity, 1))), bound)
    return bound
```

A **bin-packing lower bound**: `ceil(total demand / capacity)` per load
dimension, strongest bound wins. Ten lines, no solver, trivially portable:

```ts
// core/scenario.ts
export function theoreticalFloor(trips: Trip[], seats: number): number {
  const pax = trips.reduce((a, t) => a + t.seatsUsed, 0)
  return Math.ceil(pax / seats)
}
```

**Why this is a strong demo move.** Show three numbers, not two:

```
Baseline 174 cabs  →  PoolIQ 138 cabs  →  Theoretical floor 50 cabs
```

It tells the judge you know the difference between *your* result and the
*best possible* result, and that the remaining gap is constraints — safety,
SLA, driver hours — not laziness. Almost no hackathon team can state its own
optimality gap. It also pre-empts "could you do better?" with "yes, and here's
exactly what's stopping us, by name."

---

## 5. `PenaltyManager` — the idea, not the code

`PenaltyManager.py:14` — `PenaltyParams(solutions_between_updates,
penalty_increase, penalty_decrease, target_feasible, ...)`.

PyVRP searches through **infeasible** space deliberately, pricing violations
rather than forbidding them, and adapts the penalty every N iterations to hold a
target feasibility ratio. Too few feasible solutions → raise penalties; too many
→ lower them and explore harder.

Directly relevant to a design question the commute-os spec doesn't answer:
**should a blocked merge be discarded or scored?** PyVRP's answer is score it.
A merge that violates `detour-sla` by 30 seconds is not equivalent to one that
violates it by 20 minutes, and the design's `slack` field already carries that
magnitude — but the solver currently drops anything `blocked`.

Cheap improvement: keep near-miss proposals and surface them as *"blocked, 90
seconds over SLA — override?"* An admin override on a marginal violation is a
realistic enterprise feature and a strong demo beat. Hard blocks
(`gender-safety`) stay hard; soft ceilings become priced.

---

## 6. Local-search operators — the vocabulary of "improve a route"

`pyvrp/cpp/search/` header names, which are the standard VRP neighbourhood:

```
Relocate.h  RelocateWithDepot.h  RelocateDelivery.h  RelocatePickup.h
RelocateShipment.h  RelocateAlternative.h
InsertOptionalClient.h  InsertOptionalShipment.h
RemoveOptionalClient.h  RemoveOptionalShipment.h
ReplaceOptionalClient.h  ReplaceGroup.h  RemoveAdjacentDepot.h
LocalSearch.h  neighbourhood.h  PerturbationManager.h  SearchSpace.h
```

Two are worth implementing:

- **`Relocate`** — move one stop to a different position or route. This is the
  Approve/Revert primitive (and see spec 07 §5 on insertion).
- **`InsertOptionalClient` / `RemoveOptionalClient`** — add or drop an optional
  trip. Pairs with `required=False`/`prize` from §2 and with PRD edge case 10
  (cancel after approval).

`ReplaceGroup.h` swaps which member of a mutually exclusive group is served —
i.e. *"pool with Priya instead of Anil to satisfy the safety rule"*, which is a
much better UX than simply refusing.

---

## 7. Why not ship it

**Do not attempt to run PyVRP in the demo.** It needs CPython plus a compiled
C++ extension; your app is Next.js/TypeScript. Bridging costs hours and adds a
process boundary that can die on stage — precisely the risk design goal G5
("zero demo-time external dependencies") exists to prevent.

Clarke-Wright in TypeScript remains right: milliseconds, no dependency,
re-plans live on every cancellation.

If asked *"why not use a real solver?"*:

> "Clarke-Wright returns in about 2 ms, so the board re-plans every time a trip
> cancels. PyVRP's hybrid genetic search would find maybe 8% better routes in
> 30 seconds. For a live dispatch board, responsiveness beats optimality — and
> the constraint model is identical either way, so the upgrade path is a solver
> swap, not a rewrite."

That answer needs §3's mapping table to be true. It is.

---

## 8. `plotting/` — UI ideas, free

```
plot_coordinates  plot_demands  plot_instance  plot_objectives
plot_result  plot_route_schedule  plot_runtimes  plot_solution
plot_time_windows
```

Two are worth copying into the command center:

- **`plot_route_schedule`** — a per-route timeline: travel, service, waiting,
  time-window bands. This is a far better way to show an admin *why* a merge
  breaks SLA than a number in a card. A horizontal band chart per proposal.
- **`plot_time_windows`** — window coverage across all tasks. Doubles as the
  demand-shape view that motivates the Roster Reshaper pivot (`PIVOT.md` row 3).

---

## 9. Also worth knowing

- **`read.py`** parses **VRPLIB** and Solomon instances, with a `ROUND_FUNCS`
  table (`:31`) because VRP literature disagrees on rounding. If you ever want
  to *benchmark* your solver, Solomon instances are the standard set and this is
  how to load them. Not needed for the demo; useful if a judge asks how you'd
  validate quality.
- **`Statistics.py`** records `current/candidate/best × cost/feasibility` per
  iteration and dumps CSV. If you want a "solver convergence" chart, this is the
  schema.
- **`stop/`** — `FirstFeasible`, `MaxIterations`, `MaxRuntime`, `NoImprovement`,
  `MultipleCriteria`. Worth copying the *shape*: a stopping criterion is an
  object, and `MultipleCriteria` composes them. Your Clarke-Wright loop should
  take one rather than hardcoding a bound.

---

## 10. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | `theoreticalFloor()` + show three cab numbers | `core/scenario.ts`, `KpiStrip` | 30 min |
| 2 | Vector capacity `[seats, luggage, wheelchair]` | `types.ts`, `policies/seat-capacity.ts` | 30 min |
| 3 | Add `service_duration` (boarding dwell) per pickup | `types.ts`, `scenario.ts` | 20 min |
| 4 | `required` / `prize` on `Trip` for optional trips | `types.ts`, `solver.ts` | 45 min |
| 5 | Keep near-miss blocked proposals; add admin override | `policy.ts`, `SuggestionFeed` | 1 h |
| 6 | `reload_depots` equivalent — multi-wave shuttles | `metro-feeder.ts` | 1 h |
| 7 | Rename policies to PyVRP vocabulary in the trace UI | `policies/*` | 15 min |
| 8 | Route-schedule timeline per proposal | `ui/RouteSchedule.tsx` | 1½ h |
| 9 | Cite arXiv:2403.13795 in the algorithm slide | pitch | 2 min |

Items 1, 3 and 7 are under 90 minutes combined and give the biggest credibility
return. Item 8 is the best UI idea in the whole reference set.
