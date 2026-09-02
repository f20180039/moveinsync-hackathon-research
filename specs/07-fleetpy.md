# 07 — FleetPy (TUM Chair of Traffic Engineering)

**Reuse: 🟢 HIGH — the closest academic analogue to what you're building.**
`github.com/TUM-VT/FleetPy` · Python · ⭐114 · MIT · updated 2026-09-01 ·
**662 MB upstream → 4.9 MB via sparse clone**

Cloned as: `git clone --depth 1 --filter=blob:none --sparse` then
`git sparse-checkout set src docs examples`. Do not clone it whole.

## 1. What it is

An agent-based simulation framework for mobility-on-demand fleets from TU
Munich, with a peer-reviewed paper (arXiv 2207.14246). It models ride-pooling,
dispatching, EV charging, repositioning and fleet sizing at the scale of
thousands of vehicles and requests.

This is the **only reference repo that treats pooling as a fleet-control problem
rather than a matching trick** — which is what MoveInSync actually operates.

## 2. Module map — where your themes already live

```
src/fleetctrl/
├─ pooling/
│  ├─ immediate/insertion.py          ← insertion heuristic (the workhorse)
│  ├─ immediate/searchVehicles.py     ← candidate vehicle search
│  ├─ immediate/singleVehicleDARP.py  ← single-vehicle dial-a-ride
│  ├─ batch/AlonsoMora/               ← ★ the canonical pooling algorithm
│  ├─ batch/InsertionHeuristic/
│  ├─ batch/Simonetto/
│  └─ objectives.py                   ← what "better" means
├─ charging/                          ← EV charging control
├─ fleetsizing/                       ← how many vehicles are needed
├─ repositioning/                     ← idle vehicle rebalancing
├─ forecast/  planning/  pricing/  reservation/
├─ RidePoolingBatchAssignmentFleetcontrol.py
└─ SemiOnDemandBatchAssignmentFleetcontrol.py   ← ★★ feeder services
src/infra/ChargingInfrastructure.py    ← EV charging infrastructure
src/infra/{Zoning,NetworkZoning}.py    ← zone modelling
```

## 3. `SemiOnDemandBatchAssignmentFleetcontrol` — your Metro Feeder Mesh

"Semi-on-demand" = a service with a **fixed backbone plus flexible ends**.
That is precisely Metro Feeder Mesh: metro is the fixed trunk, feeder shuttles
are the demand-responsive ends.

Two things this buys you:

1. **A name from the literature.** "Semi-on-demand feeder service" is an
   established term with published research behind it. Saying that instead of
   "we merge cabs to metro stations" changes how your idea is received.
2. **Confirmation the composition is sound.** The design's step 7 (pool the
   feeder legs with Solver A) is the standard structure, not an improvisation.

`SoDZonalBatchAssignmentFleetcontrol.py` adds zonal variants — relevant since
commute-os is already zone-based.

## 4. Alonso-Mora — the algorithm to cite

`src/fleetctrl/pooling/batch/AlonsoMora/` implements the **request-trip-vehicle
(RTV) graph** method from Alonso-Mora et al., *PNAS* 2017 — the reference
algorithm for high-capacity ride pooling (the "3,000 taxis can serve 98% of
New York demand" paper).

Structure: build feasible trips from request cliques, build an RTV graph, then
solve an ILP for the assignment.

**Don't implement it in 14 hours.** But know it exists and where you stand
relative to it. If a judge asks "how does this scale to real fleets?":

> *"Clarke-Wright is a construction heuristic — right for a live board that
> re-plans on every cancellation. At MoveInSync's scale you'd move to an
> Alonso-Mora RTV formulation, which is what FleetPy implements. Our policy
> engine is the part that transfers unchanged, because it's independent of the
> assignment algorithm."*

That answer demonstrates you know the ceiling and that your architecture reaches
it. Very few hackathon teams can say where their approach stops being right.

## 5. `insertion.py` — the practical alternative to re-solving

`src/fleetctrl/pooling/immediate/insertion.py`: given a vehicle with a committed
plan and a new request, find the cheapest feasible insertion into the existing
stop sequence — respecting time windows and capacity.

**This is what you actually want for the live-approval flow.** Approving a merge
shouldn't re-run the whole solver; it should insert one trip into one route and
re-check constraints. Sketch:

```ts
// solvers/insert.ts — for the Approve action, not the batch Run
function cheapestInsertion(plan: Stop[], trip: Trip, policies: Policy[]) {
  let best = null
  for (let i = 0; i <= plan.length; i++) {          // every position
    const cand = buildCandidate([...plan.slice(0,i), stopFor(trip), ...plan.slice(i)])
    const trace = evaluate(cand, world, ctx)
    if (!trace.blocked && cand.km < (best?.km ?? Infinity)) best = { i, cand, trace }
  }
  return best
}
```

Pairs directly with PRD edge case 10 (cancel after approval → re-dispatch):
removal and re-insertion are the same primitive.

## 6. Also worth a look

- `src/fleetctrl/pooling/objectives.py` — how the literature weighs km vs
  waiting time vs served requests. Sanity-check `ledger.MODEL` against it.
- `src/infra/ChargingInfrastructure.py` — if the statement turns out to be
  EV/range-focused, charging-window scheduling is already modelled here.
- `src/fleetctrl/fleetsizing/` — pairs with PyVRP's `minimise_fleet` for the
  "how many cabs do we actually need" metric.
- `Input_Parameters.md` — a long list of parameters a *real* pooling system
  needs. Excellent checklist for "what did we forget."

## 7. What to ignore

The simulation harness (`run_scenarios.py`, `FleetPy_gym.py`, `RL_test.py`),
GUI, plotting, network preprocessing. It needs geopandas/shapely/pyproj — a
scientific Python stack you will not stand up on hackathon day.

## 8. Verdict

Read for **three things**: the term *semi-on-demand feeder service* (§3), the
insertion heuristic for the approve/revert flow (§5), and Alonso-Mora as your
stated scaling path (§4). Port only the insertion heuristic. The rest is
vocabulary and credibility — which is exactly what a 14-hour build can't
generate on its own.
