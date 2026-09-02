# commute-os — Design Spec v1.0

**Date:** 2026-09-02
**Status:** Approved for planning
**Author:** anshuman.singh@healthplix.com (with Claude)

---

## 1. Context

MoveInSync runs a mobility hackathon (Bessemer Tech Catalyst, first edition,
Bengaluru, ~2026-09-05). The exact problem statement is **not known in advance**.
Historical themes: Traffic Decongestion, Green Commute & Range Improvement, Mass
Transit, Carpooling, safety of women, cost, no-shows.

Building a specific product in advance is a bet likely to be lost. Instead this
kit pre-builds the **substrate every plausible statement shares**, plus two hero
solvers, so that on the day the work is *one solver file + fixture tuning* rather
than R&D.

Observation that drives the design: every MoveInSync theme reduces to the same
shape — **trips in a city + constraints + a solver + before/after KPIs on a map**.

### 1.1 What this repo is NOT

`commute-os` is a **reference kit**, not the hackathon submission. On the day a
**separate repo** is created and code is *copied* from here. Therefore:

- Files must be **liftable in isolation** — copy one file, it works.
- Code must be **boringly explicit** — no DI, no clever generics, no indirection
  an agent has to trace across files.
- A **manifest** must exist so an agent is pointed at 3 files, not a crawl.

This is a hard constraint, not a preference: it exists to minimise LLM token
consumption and wall-clock on hackathon day.

---

## 2. Goals

- G1: A running Next.js command center demonstrating baseline vs optimised
  commute plans over a synthetic Bengaluru world.
- G2: Two working solvers — **Pool Merger** (floor) and **Metro Feeder Mesh**
  (swing) — that compose.
- G3: A declarative **policy engine** with auditable traces, so constraints are
  table rows, not `if` statements, and *refusals* are demoable.
- G4: A **visible cost & carbon model** so every rupee and kilogram claimed on
  stage is traceable to a labelled constant.
- G5: **Zero demo-time external dependencies.** No API key, billing, or quota may
  be able to kill the demo.
- G6: Reference ergonomics: `KIT.md`, `PIVOT.md`, per-file headers, golden tests.

## 3. Non-goals

- No auth, no database, no persistence beyond in-memory + JSON fixtures.
- No driver app, no employee app. Admin command center only.
- No real-time traffic re-routing.
- No production hardening, no deployment pipeline, no multi-tenancy.
- Not aiming for optimal solutions — good heuristics with defensible provenance.

---

## 4. Architecture

Single Next.js 14 app (App Router), TypeScript, Tailwind. State in memory.
Data from JSON fixtures. Pinned to Next 14 for Node 18.19 compatibility.

```
commute-os/
├─ KIT.md                     # one-screen index: every file, 1 line, "copy when…"
├─ PIVOT.md                   # statement → solver → files → what to change → hours
├─ docs/
│  ├─ superpowers/specs/      # this spec
│  └─ DEMO-SCRIPT.md          # 3-minute beat sheet template
├─ data/
│  ├─ bengaluru.world.json    # zones, offices+gates, metro lines/stations, depots,
│  │                          #   drivers, vehicles, employees
│  ├─ trips.200.json          # seeded deterministic trips
│  └─ routes.cache.json       # precomputed polylines + distances, pair-keyed
├─ src/
│  ├─ core/                   # problem-agnostic. ZERO React imports.
│  │  ├─ types.ts             # THE contract — read this file = know the domain
│  │  ├─ geo.ts               # haversine, zone lookup, straight-line×1.3 fallback
│  │  ├─ routing.ts           # RouteProvider: cache → Google → haversine
│  │  ├─ clock.ts             # sim clock: play/pause/scrub/speed
│  │  ├─ policy.ts            # engine + trace types
│  │  ├─ policies/            # 9 rules, one pure function per file
│  │  ├─ ledger.ts            # ONE constants object: every ₹ and kgCO₂
│  │  └─ scenario.ts          # baseline vs solved vs diff
│  ├─ solvers/
│  │  ├─ solver.ts            # the Solver interface
│  │  ├─ pool-merger.ts       # Clarke-Wright savings + policy gate
│  │  └─ metro-feeder.ts      # feeder mesh; composes pool-merger
│  ├─ ai/sarvam.ts            # chat + Mayura + Bulbul, each with hard fallback
│  └─ ui/
│     ├─ MapCanvas.tsx        # MapLibre, deterministic geometry
│     ├─ KpiStrip.tsx         # occupancy, km, ₹, kgCO₂
│     ├─ SuggestionFeed.tsx   # proposal cards + approve/reject
│     ├─ PolicyTrace.tsx      # the 9 verdicts, pass/warn/block + slack
│     ├─ CostModelPanel.tsx   # renders ledger MODEL — answers "where's ₹410 from?"
│     └─ ScenarioBar.tsx      # clock, Run, no-show & traffic sliders
├─ app/
│  ├─ page.tsx                # command center
│  └─ api/{solve,explain,translate}/route.ts
└─ scripts/generate-fixtures.ts
```

### 4.1 Dependency rules (enforced by review, tested by import lint)

- `core/*` imports nothing from `solvers/`, `ui/`, `app/`, `ai/`.
- `solvers/*` import only from `core/*`. **Never** from each other except the one
  documented composition: `metro-feeder` may import `pool-merger`.
- `ui/*` imports only from `core/types` and `core/ledger`. No solver logic in UI.
- No file exceeds ~250 lines. If it does, it is doing too much.

### 4.2 Per-file header (mandatory, every source file)

```ts
/**
 * PURPOSE: one sentence.
 * PIVOT: what to change if the problem statement is about X.
 * SAFE-TO-DELETE: yes | no — <reason>
 */
```

This header is the token-economy mechanism. An agent reads headers, not bodies.

---

## 5. Domain model (`core/types.ts`)

Single file, all domain types, no logic. Sketch:

```ts
type LatLng = { lat: number; lng: number }
type Fuel = 'ICE' | 'CNG' | 'EV'
type Direction = 'login' | 'logout'

type Zone     = { id, name, polygon: LatLng[], centroid: LatLng, confidence: number }
type Gate     = { id, name, at: LatLng }
type Office   = { id, name, at: LatLng, gates: Gate[] }
type Employee = { id, name, gender: 'F'|'M'|'X', homeAt: LatLng, zoneId, officeId,
                  noShowRate: number }        // 0..1, historical
type Vehicle  = { id, plate, seats: number, fuel: Fuel, rangeKm?: number,
                  socPct?: number }           // rangeKm/socPct only for EV
type Driver   = { id, name, dutyMinutesToday: number, score: number }
type Depot    = { id, name, at: LatLng }

type MetroStation = { id, name, at: LatLng, lineIds: string[], order: number }
type MetroLine    = { id, name, colour, stationIds: string[], headwayMin: number }

type Trip = {
  id: string
  employeeIds: string[]
  pickupAt: LatLng
  zoneId: string
  officeId: string
  gateId: string
  direction: Direction
  windowStart: number          // epoch ms — earliest acceptable pickup
  windowEnd: number            // epoch ms — latest acceptable pickup
  seatsUsed: number
  vehicleId: string
  driverId: string
  isNightShift: boolean        // pickup or drop falls in 21:00–06:00
}

type World = { zones, offices, employees, vehicles, drivers, depots,
               metroLines, metroStations }

// --- solver/policy plumbing -------------------------------------------------

type Savings = {
  km: number                   // cab-km removed
  inr: number                  // rupees, per ledger.MODEL
  co2Kg: number
  minutesAdded: number         // worst-case detour imposed on any passenger
  p10Inr: number               // savings if the no-show risk lands badly
  p90Inr: number
}

// What a policy is handed: a proposed grouping, already routed & costed.
type Candidate = {
  tripIds: string[]
  trips: Trip[]                // resolved, in proposed pickup order
  vehicleId: string
  driverId: string
  km: number
  minutes: number
  perPassengerAddedMin: Record<string, number>  // employeeId -> detour minutes
  gateIds: string[]            // distinct gates touched, in visit order
  seatsUsed: number
}

// Ambient state a policy may need but must not fetch itself (keeps it pure).
type PolicyCtx = {
  now: number                  // sim clock, never Date.now()
  zoneRejections: Record<string, number>   // zoneId -> admin reject count
  trafficMultiplier: number    // 1.0 = nominal, from ScenarioBar slider
  noShowOverride?: number      // slider override of employee.noShowRate
}
```

`Trip.employeeIds` is an array from the start — a merged trip is a Trip, not a
special case. This avoids a refactor on the day.

---

## 6. Core modules

### 6.1 `geo.ts`

- `haversineKm(a, b)`
- `pointInZone(p, zone)` — ray casting
- `nearestN(p, points, n, maxKm)`
- `estimateKm(a, b)` — `haversineKm × 1.3` road-factor fallback (PRD edge case 8)

### 6.2 `routing.ts`

```ts
interface RouteProvider {
  route(a: LatLng, b: LatLng): Promise<{ km, minutes, polyline: LatLng[], source }>
}
```

Resolution order, always in this order:
1. `routes.cache.json` lookup by rounded pair key → `source: 'cache'`
2. Google Directions **only if** `NEXT_PUBLIC_ENABLE_LIVE_ROUTING=true` → `'google'`
3. `estimateKm` straight-line×1.3, synthetic 2-point polyline → `'estimate'`

`source` is surfaced in the UI: `'estimate'` renders a **dotted** line labelled
"Estimated route". Google is never on the critical path. This satisfies G5.

### 6.3 `clock.ts`

Simulation clock over a fixed demo day. `play/pause/seek(t)/setSpeed(1|5|20)`,
subscriber callbacks. Drives cab animation and any before/after playback. Not
`Date.now()` anywhere in `core` — determinism is required for golden tests.

### 6.4 `ledger.ts` — the cost & carbon model

One exported object. Every value labelled as a tunable assumption with its
derivation. Initial values:

| Constant | Value | Basis |
|---|---|---|
| `cabRatePerKm` | ₹18 | typical Bengaluru corporate sedan contract |
| `cabBaseFarePerTrip` | ₹60 | fixed per-dispatch component |
| `shuttleRatePerKm` | ₹26 | 12-seater; cheaper *per passenger* |
| `shuttleSeats` | 12 | — |
| `driverCostPerHour` | ₹180 | — |
| `metroFarePerTrip` | ₹30 | BMRCL mid-distance |
| `co2SedanPerKm` | 0.142 kg | petrol sedan, ~6.1 L/100km × 2.31 kg/L |
| `co2SuvPerKm` | 0.186 kg | — |
| `co2ShuttlePerKm` | 0.680 kg | 12-seater diesel |
| `co2EvPerKm` | 0.100 kg | 0.14 kWh/km × ~0.71 kg CO₂/kWh India grid mix |
| `co2MetroPerPassengerKm` | 0.014 kg | electrified rail, high load factor |

**Honesty note that must survive into the UI:** an EV on the Indian grid is
~0.10 vs ~0.14 kg/km for petrol — a ~30% cut, not zero. Claiming "EV = zero
carbon" is the kind of thing a judge catches. Metro is the real carbon win, which
is precisely why Metro Feeder Mesh is the swing solver.

`CostModelPanel.tsx` renders this table live. "Where does ₹410 come from?" becomes
a click.

### 6.5 `scenario.ts`

```ts
type Metrics = { cabKm, shuttleKm, metroPaxKm, vehiclesUsed, avgOccupancyPct,
                 costInr, co2Kg, slaViolations }
type Scenario = { baseline: Metrics, solved: Metrics, diff: Metrics,
                  proposals: Proposal[] }
```

`computeMetrics(trips, world)` is the single source of every number on screen.
`diff` is computed, never hand-written.

Also hosts the **counterfactual sliders**: `noShowRate` and `trafficMultiplier`
re-run metrics to produce `p10 / expected / p90` savings. Savings render as a
range, never a point estimate.

---

## 7. Policy engine — the moat

```ts
type PolicyStatus  = 'pass' | 'warn' | 'block'
type PolicyVerdict = { id, name, status: PolicyStatus,
                       slack?: { value: number; unit: string }, reason: string }
type PolicyTrace   = { verdicts: PolicyVerdict[], blocked: boolean }

type Policy = (c: Candidate, w: World, ctx: PolicyCtx) => PolicyVerdict
```

`Candidate` = a proposed grouping of trips + its computed route. Policies are
**pure functions**, one per file, individually unit-tested. `evaluate()` runs all
nine and returns the trace; `blocked = verdicts.some(v => v.status === 'block')`.

| id | Rule | Verdict |
|---|---|---|
| `gender-safety` | Night shift (21:00–06:00) and merged group has exactly **1** female → **block**. ≥2 females or 0 females → pass. Also: a lone female may not be the **last drop** on a night logout → block. | block |
| `detour-sla` | Added travel time for each already-assigned passenger ≤ `min(10 min, 30% of their original duration)`. `slack` = minutes remaining. | block |
| `driver-hours` | `dutyMinutesToday + mergedDuration ≤ 720` (12 h). Warn above 660. | block / warn |
| `ev-range` | If `fuel === 'EV'`: `mergedKm ≤ rangeKm × 0.8` (20% reserve). On block, reason names the CNG/ICE reassignment. | block |
| `seat-capacity` | `Σ seatsUsed ≤ vehicle.seats`. | block |
| `gate-spread` | Multiple office gates allowed; +5 min per extra gate, max 2 distinct gates. >2 → block. Feeds its penalty into `detour-sla`. | block |
| `time-window` | Pickup windows must overlap within 15 min. | block |
| `zone-confidence` | Zone rejected ≥3 times → warn, and the solver de-prioritises that zone. Never blocks. | warn |
| `no-show-risk` | Computes expected vs p10 savings from `employee.noShowRate`. Never blocks. | warn |

Design intent: the nine PRD edge cases become **data**. Adding a tenth rule on
the day is one file plus one array entry — no solver changes. And the UI renders
refusals, which is the single most memorable demo beat available (no other team
demos their system *declining* to act).

---

## 8. Solver interface

```ts
type SolverInput  = { world: World, trips: Trip[], policies: Policy[],
                      now: number, params?: Record<string, number> }
type Proposal     = { id, kind: 'merge' | 'feeder', tripIds: string[],
                      geometry: LatLng[], routeSource: 'cache'|'google'|'estimate',
                      trace: PolicyTrace, savings: Savings,
                      explanation?: string,
                      status: 'suggested' | 'approved' | 'rejected' }
type SolverResult = { proposals: Proposal[] } & Scenario

interface Solver { id: string; name: string; run(i: SolverInput): SolverResult }
```

Adding a solver on the day = implement this interface in one file, register it in
one array. That is the entire pivot surface.

---

## 9. Solver A — Pool Merger (the floor)

Clarke-Wright savings, adapted to the **convergent single-destination** case
(many pickups, one office), which is what employee login transport actually is.

### 9.1 Derivation (must be reproducible on stage)

Classic Clarke-Wright for a depot `O`: merging routes `O→i→O` and `O→j→O` into
`O→i→j→O` saves `d(i,O) + d(O,j) − d(i,j)`.

Employee commute is one-directional and convergent — pickups `i`, `j` both end at
office `O`:

- Original (two cabs): `d(i,O) + d(j,O)`
- Merged (one cab, `i` first): `d(i,j) + d(j,O)`
- Savings: `d(i,O) + d(j,O) − d(i,j) − d(j,O) = d(i,O) − d(i,j)`

Pick the better pickup order:

```
s(i,j) = max( d(i,O), d(j,O) ) − d(i,j)
```

**Read it in words:** pooling saves the *longer* of the two solo hauls, minus the
cost of the connector. Intuitive, and it is a genuine CW adaptation, not a
heuristic invented on the spot.

### 9.2 Algorithm

1. Group trips by `(officeId, direction, overlapping time window)`.
2. Within each group, compute `s(i,j)` for all pickup-chain endpoint pairs.
3. Sort descending.
4. Greedily merge the best pair while `evaluate()` returns `blocked === false`
   and capacity allows. Merging chains (not just pairs) yields **3- and 4-seat
   fills**, which is where the real money is.
5. Re-evaluate endpoints after each merge; repeat until no positive-savings,
   non-blocked pair remains.
6. Emit a `Proposal` per merge, each carrying its full `PolicyTrace` — including
   the merges that were **rejected** and why.

### 9.3 Why this survives questioning

*"Is this optimal?"* → "No. It's the Clarke-Wright savings heuristic, the
standard VRP construction method since 1964, typically within 5–10% of optimal,
and it runs in milliseconds on 200 trips so it re-plans live as trips cancel."
That is a real answer. A greedy pairwise matcher has none.

---

## 10. Solver B — Metro Feeder Mesh (the swing)

Premise: point-to-point cabs across Bengaluru are the wrong primitive when three
metro lines now cover the major employment corridors. Replace the *long haul*
with metro; use vehicles only for the first and last mile — **and pool those**.

### 10.1 Algorithm

For each trip `t` with pickup `P`, office `O`, gate `g`:

1. `directKm, directMin ← route(P, O)`
2. Boarding candidates `B` = stations within `FEEDER_RADIUS_KM` (6) of `P`
3. Alighting candidates `A` = stations within `LAST_MILE_RADIUS_KM` (3) of `O`
4. For each `(b, a)` connected on the metro graph:
   - `metroMin = stops × 2.2 + (interchange ? 5 : 0)`
   - `waitMin = headwayMin / 2`
   - `totalMin = feederMin + waitMin + metroMin + lastMileMin`
   - `cabKmSaved = directKm − d(P,b) − d(a,O)`
5. **Accept** if `totalMin ≤ directMin + MAX_EXTRA_MIN` (15)
   **and** `cabKmSaved ≥ MIN_KM_SAVED` (2)
6. Keep the `(b, a)` maximising `cabKmSaved`
7. **Compose:** group accepted feeder legs by `(boardingStation, 10-min bucket)`
   and run **Solver A** over them → shared feeder shuttles instead of solo cabs
8. Policy-gate each shuttle group (same nine rules; `seat-capacity` uses
   `shuttleSeats = 12`)

Step 7 is the elegant part and the headline: the two solvers compose, and the
claim becomes **"we deleted N% of cab-kilometres"** — not "we saved 8.2 km".

### 10.2 Metro graph fixtures

Three lines, with interchanges:

- **Purple** — Whitefield (Kadugodi) ↔ Challaghatta
- **Green** — Madavara ↔ Silk Institute
- **Yellow** — RV Road ↔ Bommasandra *(serves the Electronic City / Bommasandra
  corridor — the single most relevant line for employee transport)*
- Interchanges: Kempegowda/Majestic (Purple↔Green), RV Road (Green↔Yellow)

**Assumption to verify:** station coordinates in `bengaluru.world.json` are
approximations entered by hand. They are good enough for a synthetic demo and
must be spot-checked before the event. Flagged in §17.

---

## 11. Fixtures

`scripts/generate-fixtures.ts` — seeded PRNG (fixed seed, committed output) so
every run and every test is byte-identical.

Produces:
- 6 zones: Koramangala, Bellandur, Indiranagar, Whitefield, Electronic City, HSR
- 4 offices, 2–3 gates each
- 200 employees with `gender`, `homeAt` clustered in zones, `noShowRate` 0.02–0.25
- 40 vehicles: mix of ICE/CNG/EV (EVs with `rangeKm` 120–180, varied `socPct`)
- 25 drivers with varied `dutyMinutesToday` (several deliberately near the 12 h cap)
- 200 trips across login and logout, including a **night-shift cohort** so
  `gender-safety` has something real to block
- `routes.cache.json` for every pair the fixtures need

Fixtures are **deliberately adversarial**: they contain cases that trip each of
the nine policies, so the demo can show refusals without staging them live.

---

## 12. UI shell

Layout follows the original PRD instinct — map left, feed and dashboard right.

- `MapCanvas` — MapLibre GL + OSM raster tiles. Baseline routes grey, solved
  routes blue, metro lines in line colours, `'estimate'` routes dotted. Cab
  markers animated off `clock.ts`. Occupancy badges (`2/4`).
- `ScenarioBar` — clock (play/pause/scrub/speed), **Run Solver** selector,
  no-show and traffic sliders.
- `KpiStrip` — occupancy %, cab-km, ₹, kg CO₂, each as `baseline → solved (Δ)`.
- `SuggestionFeed` — proposal cards with savings **range**, Approve / Reject /
  View on Map / Translate. Reject feeds `zone-confidence`.
- `PolicyTrace` — the nine verdicts with pass/warn/block and remaining slack.
  **Blocked proposals are shown, not hidden.**
- `CostModelPanel` — collapsible, renders `ledger.MODEL`.
- **Revert** action on any approved proposal — un-pools and re-dispatches the
  original cabs (PRD edge case 10). Lives on the approved card in the feed.

Approve applies the proposal to in-memory trip state; metrics and map re-render
from `scenario.ts`. Revert un-pools (PRD edge case 10).

---

## 13. AI layer (`ai/sarvam.ts`)

Three functions, each `try/catch` returning a **pre-written deterministic
fallback** rather than throwing:

- `explainProposal(p)` → Sarvam chat → `{ adminReason, employeeMessage }`
- `translate(text, lang)` → Mayura (`kn-IN`, `ta-IN`, `hi-IN`) → English + toast
  on failure (PRD edge case 7)
- `speak(text, lang)` → Bulbul TTS → silent no-op on failure

Env-gated by `SARVAM_API_KEY`; absent key means fallbacks, and the UI still works
end to end. **The stage demo cannot depend on a network call.**

The nudge is framed as a **negotiation** — the employee message asks for
acceptance, and Reject/decline feeds back into `zone-confidence`, closing the
loop engine → employee → engine. This is deliberately more than decorative
translation.

---

## 14. Error handling

| Failure | Behaviour |
|---|---|
| Route cache miss, live routing off | `estimate` (haversine × 1.3), dotted line, labelled |
| Google Directions error / ZERO_RESULTS | fall through to `estimate` |
| Sarvam chat down | pre-written explanation string, no UI error |
| Mayura unsupported language | English + toast |
| Bulbul down | silent no-op |
| Solver finds nothing | empty-state card: "No poolable trips in this window" — never a spinner that never ends |
| Fixture load failure | hard fail at boot with a clear message (dev-time only) |

Principle: **no failure path is allowed to blank the screen.**

---

## 15. Testing

Vitest. TDD — tests first for every `core` and `solvers` module.

- `geo.ts` — known-distance assertions, zone containment edges
- each of the 9 policies — pass, warn, and block cases per rule (27+ tests).
  These are cheap, fast, and are the highest-value tests in the repo.
- `ledger.ts` — cost and CO₂ arithmetic against hand-computed values
- `scenario.ts` — diff correctness; p10/expected/p90 ordering
- `pool-merger` — golden fixture: `200 trips → ≥30 km saved`, plus the CW
  savings formula against a hand-worked 3-node example
- `metro-feeder` — golden fixture on cab-km deleted; asserts the composition
  step actually pools feeder legs
- import-boundary test asserting §4.1 dependency rules

Golden tests double as **executable documentation of solver intent** — which is
the mechanism that stops an agent re-deriving behaviour on the day. This is a
token-economy feature, not just hygiene.

---

## 16. Reference-ergonomics artifacts

These are deliverables, not documentation afterthoughts. They are the reason the
kit exists.

**`KIT.md`** — one screen. Every file, one line: what it does, and "copy when…".

**`PIVOT.md`** — the playbook. One row per likely statement:

| If the statement is about… | Use | Copy | Change | Est. |
|---|---|---|---|---|
| carpooling / occupancy / cost | Pool Merger | `core/*`, `pool-merger` | fixtures, ledger rates | 3 h |
| mass transit / first-last mile | Metro Feeder | `core/*`, both solvers | metro fixtures, radii | 4 h |
| decongestion / shift timing | new `roster-reshaper` | `core/*`, `scenario` | new solver, sweep windows | 3 h |
| women's safety | policy-led | `core/*`, `policies/gender-safety` | promote policy to hero, add geofence | 2 h |
| EV / range / green | policy-led | `core/*`, `policies/ev-range`, `ledger` | EV assignment solver | 3 h |
| no-shows / dead km | `scenario` sliders | `core/*`, `scenario` | predictor fn | 2 h |

**`docs/DEMO-SCRIPT.md`** — 3-minute beat sheet: problem (20 s), baseline board
(20 s), run solver (30 s), **the refusal** (30 s), the compose/headline number
(40 s), the nudge loop (20 s), cost model (20 s).

---

## 17. Assumptions to verify before the event

1. **Metro station coordinates** in `bengaluru.world.json` are hand-approximated
   and must be spot-checked.
2. **Ledger constants** (§6.4) are industry-typical, not MoveInSync's actuals.
   All are labelled as assumptions in the UI.
3. **Hackathon rules on pre-existing code.** This kit must have commit history
   clearly pre-dating the event, and the framing should be stated openly to
   judges: the kit is a generic sandbox; the solver and policies are the event
   work. Confirm the rules permit it.
4. **Node 18.19** is installed; Next.js pinned to 14 accordingly.
5. **Metro headways and stop times** (2.2 min/stop, headway/2 wait) are
   estimates, labelled in the UI.

---

## 18. Build order

Value density descending. If time runs out, everything above the cut still stands
alone as reference.

1. `core/types.ts`, `geo.ts`, `ledger.ts` + tests
2. `policy.ts` + all 9 policies + tests ← **highest reference value**
3. `scenario.ts`, `clock.ts`, `routing.ts` + tests
4. `scripts/generate-fixtures.ts` → the three JSON files
5. `solvers/pool-merger.ts` + golden tests ← **the floor, must exist**
6. `solvers/metro-feeder.ts` + golden tests ← **the swing**
7. `ai/sarvam.ts` with fallbacks
8. UI shell: `MapCanvas`, `KpiStrip`, `SuggestionFeed`, `PolicyTrace`,
   `ScenarioBar`, `CostModelPanel`
9. `app/page.tsx` + API routes
10. `KIT.md`, `PIVOT.md`, `DEMO-SCRIPT.md`

**Cut line: after step 6.** Steps 1–6 are the kit's actual worth; 7–10 make it
demoable.
