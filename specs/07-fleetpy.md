# 07 — FleetPy · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/TUM-VT/FleetPy` — TU Munich, Chair of Traffic Engineering |
| **Reuse** | 🟢 **HIGH** — the closest academic analogue to what you're building |
| **Stack** | Python · numpy/pandas · geopandas/shapely/pyproj · optional Gurobi/CPLEX |
| **Size** | **662 MB upstream → 4.9 MB sparse** · ⭐114 · MIT · updated 2026-09-01 |
| **Paper** | arXiv:2207.14246 — *"FleetPy: A Modular Open-Source Simulation Tool for Mobility On-Demand Services"* |
| **Local** | `reference/fleetpy/` (sparse: `src docs examples`) |

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/TUM-VT/FleetPy.git
git -C FleetPy sparse-checkout set src docs examples
```

Do **not** clone whole — the bulk is scenario data you don't need.

This is the only reference repo that treats pooling as a **fleet-control
problem** rather than a matching trick, which is what MoveInSync actually
operates.

---

## 1. Architecture

Agent-based simulation: a time-stepped loop where an operator (fleet control)
receives requests, makes offers, assigns vehicles, and moves them on a network.

```
run_scenarios.py                      entry point, scenario sweeps
FleetSimulationBase.py                the simulation loop
ImmediateDecisionsSimulation.py       decide per request as it arrives
BatchOfferSimulation.py               batch requests, then decide
src/fleetctrl/
├─ FleetControlBase.py                operator interface
├─ pooling/
│  ├─ immediate/
│  │  ├─ insertion.py            ★★★ 630 lines — the workhorse (§3)
│  │  ├─ searchVehicles.py            candidate vehicle pre-filter
│  │  ├─ SelectRV.py                  request-vehicle pair selection
│  │  └─ singleVehicleDARP.py         exact single-vehicle dial-a-ride
│  ├─ batch/
│  │  ├─ AlonsoMora/              ★★  RTV-graph pooling (§4)
│  │  ├─ InsertionHeuristic/          batch + zonal insertion
│  │  └─ Simonetto/                   linear-assignment variant
│  ├─ objectives.py              ★★  what "better" means (§5)
│  └─ GeneralPoolingFunctions.py
├─ SemiOnDemandBatchAssignmentFleetcontrol.py   ★★★ feeder services (§2)
├─ SoDZonalBatchAssignmentFleetcontrol.py       zonal variant
├─ RidePoolingBatchAssignmentFleetcontrol.py
├─ charging/{ChargingBase,Threshold}.py         EV charging control
├─ fleetsizing/{TimeBased,UtilizationBased}FS.py
├─ repositioning/                     idle vehicle rebalancing
├─ forecast/ planning/ pricing/ reservation/
src/infra/
├─ ChargingInfrastructure.py          depots, chargers, queues
├─ BoardingPointInfrastructure.py     designated stops
└─ {Zoning,NetworkZoning}.py
src/routing/ src/demand/ src/evaluation/
Input_Parameters.md                   ★ every parameter a real system needs
```

---

## 2. `SemiOnDemandBatchAssignmentFleetcontrol` — Metro Feeder Mesh, named

`src/fleetctrl/SemiOnDemandBatchAssignmentFleetcontrol.py:682`

> "Combined fleet control for **semi-on-demand flexible & fixed route**."

Semi-on-demand = a **fixed backbone with demand-responsive ends**. Metro is the
fixed trunk; feeder shuttles are the flexible ends. That is Metro Feeder Mesh,
and it has a name in the literature with published research behind it.

Two things this buys you:

1. **Vocabulary.** "A semi-on-demand feeder service with pooled first-mile legs"
   lands very differently from "we merge cabs to metro stations."
2. **Validation.** The design's step 7 — pool the feeder legs with Solver A — is
   the standard structure for this service class, not an improvisation.

`SoDZonalBatchAssignmentFleetcontrol.py:192` subclasses it for **zonal**
operation, which matters because commute-os is already zone-based.

### Two parameters worth stealing outright

From the constructor docstring (`:691-696`):

**`user_max_wait_time_2`** —
> "if the user couldn't be assigned in the first try, it will be considered
> again in the next opt-step with this new max_waiting_time constraint"

A **two-tier SLA**: attempt assignment under a strict wait limit; if that fails,
retry with a relaxed one. The commute-os `detour-sla` policy is a single
threshold (10 min / 30%). Making it two-tier is more realistic *and* a better
demo: *"12 trips couldn't pool under our 10-minute promise; 9 of them pool if we
relax to 15, and here's the saving that unlocks — your call."* That's a decision
put to the admin, which is what a command center is for.

**`user_offer_time_window`** —
> "after accepting an offer the pick-up time is constrained around the expected
> pick-up time with an interval of the size of this parameter"

Once an employee **accepts**, the system commits to ±N minutes around the quoted
pickup. This is the missing half of the design's negotiation nudge (§13): the
nudge currently asks for acceptance but promises nothing in return. A commitment
window is what makes acceptance rational, and it converts the nudge from a
notification into a contract.

---

## 3. `insertion.py` — the primitive to actually port

`src/fleetctrl/pooling/immediate/insertion.py:17`

```python
def simple_insert(routing_engine, sim_time, veh_obj, orig_veh_plan,
                  new_prq_obj, std_bt, add_bt,
                  skip_first_position_insertion=False) -> List[VehiclePlan]:
    """Inserts the stops for the new request at all possible positions of
    orig_veh_plan and returns a generator that only yields the feasible
    solutions and None in the other case."""
```

Given a vehicle with a **committed plan** and one new request, try inserting its
pickup and drop-off at every feasible position pair, yielding only
constraint-satisfying plans.

**This is what the Approve action needs.** Approving a merge should not re-run
the whole solver; it should insert one trip into one route and re-check
constraints. And `simple_remove` (`:228`) is its inverse — exactly PRD edge case
10 (cancel after approval → un-pool and re-dispatch). Insertion and removal are
the same primitive, which is why Revert is nearly free once you have Approve.

### Three implementation details worth copying

**3.1 `std_bt` vs `add_bt`** — "standard boarding time" and "**additional**
boarding time for an extra request". Boarding has a fixed cost per stop plus a
marginal cost per extra passenger.

This is independently the same distinction as VROOM's `setup` vs `service`
(spec 06 §6.4). **Two unrelated production systems model boarding this way**, so
it isn't incidental: two colleagues at the same gate cost
`std_bt + 2×add_bt`, not `2×std_bt`. Same-building pooling is cheaper than the
current design models — which makes pooling look *better*.

**3.2 Early termination** (`:26`):

```python
o_prq_feasible = True   # once max wait time of new_prq_obj is reached,
                        # no insertion at later index will be feasible
```

Because plan stops are time-ordered, once an insertion position violates the new
request's latest pickup, **every later position also violates it** — so break
rather than continue. Turns a quadratic scan into an early-exit one. Free
optimisation, two lines.

**3.3 `skip_first_position_insertion`** — inserting before the vehicle's current
next stop is often disallowed (the cab is already en route). A real constraint
the design would otherwise miss: an approved merge cannot retroactively change a
pickup the cab has already committed to.

### Port sketch

```ts
// solvers/insert.ts
// PURPOSE: insert one trip into one committed route; the Approve/Revert primitive.
// PIVOT: this is the online counterpart to the batch Clarke-Wright run.
export function cheapestInsertion(plan: Stop[], trip: Trip, w: World, ctx: PolicyCtx) {
  let best: { at: number; cand: Candidate; trace: PolicyTrace } | null = null
  for (let i = 1; i <= plan.length; i++) {          // skip position 0: cab en route
    const cand = buildCandidate([...plan.slice(0, i), stopFor(trip), ...plan.slice(i)])
    if (cand.pickupTime(trip) > trip.windowEnd) break      // 3.2 early exit
    const trace = evaluate(cand, w, ctx)
    if (!trace.blocked && cand.km < (best?.cand.km ?? Infinity)) best = { at: i, cand, trace }
  }
  return best
}
```

Also: `single_insertion` (`:298`) inserts across a whole vehicle list;
`insertion_with_heuristics` (`:390`) and `immediate_insertion_with_heuristics`
(`:407`) layer candidate-vehicle pre-filtering on top — which is where the H3
corridor scan from spec 01 belongs in the pipeline.

---

## 4. Alonso-Mora — your stated scaling path

`src/fleetctrl/pooling/batch/AlonsoMora/`

```
AlonsoMoraAssignment.py          the assignment driver
V2RB.py                          ★ vehicle-to-request-bundle
AlonsoMoraParallelization.py     multiprocessing
MoiaAlonsoMoraParallelization.py operator-specific variant
misc.py  comcodes.py
```

Implements the **request-trip-vehicle (RTV) graph** method of Alonso-Mora et
al., *PNAS* 2017 — the reference algorithm for high-capacity ride pooling (the
"3,000 taxis can serve 98% of New York taxi demand" result).

`V2RB.py:23` names the core structure:

> "this class is a collection of feasible vehicle plan for a specific vehicle
> serving the same requests"

So a V2RB is (vehicle, request-set) → all feasible plans serving exactly that
set. Build these bottom-up over request cliques, then solve an ILP to pick one
V2RB per vehicle covering the most requests. Note `:27-30`: a V2RB can be
constructed from scratch, by inserting a new request into existing plans, or
forced-feasible from given plans — i.e. **incremental** maintenance, not
rebuild-per-tick.

**Do not implement this in 14 hours.** Know it exists and where you stand:

> *"Clarke-Wright is a construction heuristic — the right choice for a live
> board that re-plans on every cancellation. At MoveInSync's scale you'd move to
> an Alonso-Mora RTV formulation, which is what FleetPy implements: build
> feasible vehicle-request bundles, then solve an ILP over them. Our policy
> engine transfers unchanged, because it's independent of the assignment
> algorithm — it only ever answers 'is this grouping legal, and by how much'."*

Very few hackathon teams can say where their approach stops being the right one.

---

## 5. `objectives.py` — what "better" means

`src/fleetctrl/pooling/objectives.py:25` —
`return_pooling_objective_function(vr_control_func_dict)` returns a closure
scoring `(sim_time, vehicle, plan, requests, routing_engine) → float`.

Available objectives:

```
total_distance                    total_system_time      total_travel_times
user_times                        system_and_user_time   sys_time_and_detour_time
distance_and_user_times           distance_and_user_vehicle_times
distance_and_user_times_with_walk soft_time_windows      p_reassign
```

**The structural detail is that every objective ends the same way:**

```python
return sum_dist - assignment_reward         # :65
return end_time - simulation_time - assignment_reward   # :90
return sum_user_times - assignment_reward   # :143
```

A large constant `assignment_reward` is subtracted per assigned request, so
**serving a request always dominates route efficiency**. This is the same
principle as Timefold ranking `MAXIMIZE_VISITS_ASSIGNED` above
`MINIMIZE_TRAVEL_TIME` (spec 08 §4) — **two independent systems agree**, which
makes it a rule rather than a preference.

Check `core/scenario.ts` cannot reward dropping trips to look efficient. An
unserved employee must cost more than any distance saving. Easiest way to
produce an impressive-looking demo that a sharp judge dismantles in one
question.

Two objectives worth noting specifically:

- **`distance_and_user_times_with_walk`** — includes **walking** legs. Directly
  relevant: in Metro Feeder Mesh the last mile may be a walk, and its cost must
  enter the objective rather than being ignored.
- **`sys_time_and_detour_time`** — prices operator time and passenger detour
  separately. That's the real tension in pooling, and it's the right shape for
  weighing `detour-fairness` (spec 08 §3) against cost.

---

## 6. EV, charging and fleet sizing

If the problem statement lands on green/range:

- **`src/infra/ChargingInfrastructure.py`** — depots, chargers, queueing.
- **`src/fleetctrl/charging/Threshold.py`** — a threshold policy: send a vehicle
  to charge when SoC drops below X. Simple, and enough for a demo. Pairs with
  the design's `ev-range` policy: that one *blocks* a merge on range; this one
  *schedules* the fix.
- **`src/fleetctrl/fleetsizing/`** — `TimeBasedFS` (vary fleet by time of day)
  and `UtilizationBasedFS` (vary by observed utilisation). Pairs with PyVRP's
  `minimise_fleet` (spec 05 §4) for the "how many cabs do we actually need"
  metric — and `TimeBasedFS` is essentially the Roster Reshaper argument from
  the supply side.

---

## 7. `Input_Parameters.md` — a free completeness checklist

A long enumeration of every parameter a real MoD system takes. Read it as
*"what did we forget?"* rather than as configuration. Categories include
operator attributes, request generation, vehicle types, charging, zoning,
forecast horizons and optimisation intervals.

Cheapest way to find the gap in your model that a domain-expert judge will
otherwise find for you.

---

## 8. What to ignore

The simulation harness (`run_scenarios.py`, `FleetSimulationBase.py`,
`FleetPy_gym.py`, `RL_test.py`, `zip_study.py`), the Tkinter scenario GUI,
`python_plots/`, `result_analysis/`, network preprocessing. It needs
geopandas + shapely + pyproj and optionally Gurobi/CPLEX — a scientific Python
stack you will not stand up on hackathon day, and none of it ports to
TypeScript.

---

## 9. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | Port `simple_insert` + `simple_remove` for Approve/Revert | `solvers/insert.ts` | 2 h |
| 2 | Early-exit pruning in the insertion loop | same | 10 min |
| 3 | `std_bt` / `add_bt` boarding split | `types.ts`, `scenario.ts` | 20 min |
| 4 | Skip position 0 — cab already en route | `solvers/insert.ts` | 10 min |
| 5 | Two-tier SLA (`user_max_wait_time_2`) | `policies/detour-sla.ts` | 45 min |
| 6 | Commitment window after acceptance | `ai/sarvam.ts`, `SuggestionFeed` | 45 min |
| 7 | Verify no objective rewards dropping trips | `scenario.ts` | 15 min |
| 8 | Include walk legs in feeder cost | `metro-feeder.ts` | 30 min |
| 9 | Say "semi-on-demand feeder service" in the pitch | pitch | 0 |
| 10 | Read `Input_Parameters.md` as a gap checklist | — | 20 min |

Items 5 and 6 together turn the nudge into a genuine negotiation with a promise
attached — which is the difference between a notification and a product.
