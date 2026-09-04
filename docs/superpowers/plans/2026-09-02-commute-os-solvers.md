# commute-os Solvers — Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Both hero solvers on top of Plan 1's core — **Pool Merger**
(Clarke-Wright savings) and **Metro Feeder Mesh** (semi-on-demand feeder that
composes Pool Merger).

**Architecture:** `src/solvers/*` imports only `src/core/*`. One documented
exception: `metro-feeder` may import `pool-merger`, because composing them is
the design (spec §10.1 step 7).

**Spec:** `docs/superpowers/specs/2026-09-02-commute-os-design.md` v1.1 — §8, §9,
§10, and Tier A items A5, A8, A11.

**New dependency:** `h3-js` ^4.5.0 (Apache-2.0, 0 runtime deps). Never
hand-write H3.

**Verified locally 2026-09-02**, before writing this plan:
- `latLngToCell`, `cellToLatLng`, `gridPathCells`, `getResolution`, `gridDisk`,
  `cellToBoundary` all exist as named exports.
- Res-8 indexes are **fixed 15 characters** (e.g. `88618925c5fffff`) — the
  stride-based prefix scan depends on this and it holds.
- `gridPathCells` between two res-8 cells ~5.5 km apart returns 8 contiguous
  cells, all at res 8.

**And the design's central adaptation is empirically confirmed.** Two homes
converging on one Bellandur office, keyed both ways:

| Keying | Shared leading cells |
|---|---|
| **login, reversed** | **8** |
| logout, as-is | **0** |

That is spec 01 §6's inversion demonstrated rather than asserted: convergent
trips share a *suffix*, so reversing turns it into the prefix a range scan can
find. Task 3's test case 4 pins this.

## Global Constraints
Inherits Plan 1's constraints verbatim. Additionally:
- `src/solvers/**` imports only from `src/core/**` (plus `h3-js`); the sole
  exception is `metro-feeder` → `pool-merger`. Extend Plan 1's
  `tests/boundaries.test.ts` to assert this.
- Solvers are **pure**: `run(input)` must not mutate `input`. Asserted by test.
- Every proposal carries a complete `PolicyTrace`, including blocked ones —
  the UI shows refusals.

---

### Task 1: `solvers/solver.ts` + `candidate.ts` — the shared contract

**Files:** `src/solvers/solver.ts`, `src/solvers/candidate.ts`,
`tests/solvers/candidate.test.ts`

**Produces:**
- `SolverInput = { world: World; trips: Trip[]; policies: Policy[]; now: number; params?: Record<string, number> }`
- `Proposal = { id: string; kind: 'merge' | 'feeder'; tripIds: string[]; geometry: LatLng[]; routeSource: RouteSource; trace: PolicyTrace; savings: Savings; explanation?: string; status: 'suggested' | 'approved' | 'rejected' }`
- `SolverResult = { proposals: Proposal[]; baseline: Metrics; solved: Metrics; diff: Metrics }`
- `Solver = { id: string; name: string; run(i: SolverInput, rp: RouteProvider): SolverResult }`
- `buildCandidate(trips: Trip[], order: number[], vehicleId: string, driverId: string, w: World, rp: RouteProvider): Candidate`
- `soloMinutes(t: Trip, w: World, rp: RouteProvider): number`

**`buildCandidate` contract** — this is the piece every policy depends on, so
get it exactly right:
1. **Direction-aware sequence.** All trips in a candidate MUST share one
   `direction` — throw if they do not; an inbound and an outbound rider in one
   vehicle is nonsense. For `login`: visit the home-side stops in `order`, then
   the office gate(s). For `logout`: visit the gate(s) FIRST, then the home-side
   stops in `order` — the generator sets `pickupAt: emp.homeAt` for EVERY trip
   regardless of direction, so on an outbound run `pickupAt` is a DROP point and
   routing "homes then gate" is backwards. This is the same direction asymmetry
   measured for corridor keying above (login-reversed shares 8 leading cells,
   logout as-is shares 0); it applies here too. 34% of the committed fixture is
   logout, and Task 4 runs over all of it.
2. `km` = Σ leg km along that sequence.
3. `minutes` = Σ leg minutes + `boardingMinutes(distinctStops, totalPax)` from
   `core/ledger` — the per-stop/per-passenger split (A9).
   **Walk STOPS, not trips.** Build the distinct home-side locations in
   first-appearance order along `order`, each carrying the trips at it, and
   charge `boardingMinutes(1, paxAtThatStop)` once per stop; every trip at a
   stop shares that stop's elapsed time. A trip-based walk double-charges
   `setupMinPerStop` when two riders share an address, which handed two
   employees at the SAME building a 2-minute difference in
   `perPassengerAddedMin` — in the one scenario a pooling product should handle
   best. Summing per-stop boarding over the walk equals
   `distinctStops × setupMinPerStop + totalPax × serviceMinPerPassenger`, i.e.
   exactly `boardingMinutes(distinctStops, totalPax)` — so **assert that the
   walk total equals `minutes`** on a candidate with a coincident stop. That
   identity cannot hold vacuously: it ties together the two code paths that
   otherwise silently disagree.
4. `pickupTimes[tripId]` = cumulative arrival at that trip's HOME-SIDE stop —
   board time inbound, drop time outbound — starting from the earliest window
   start across the group — computed over the candidate's OWN members
   (`order.map(i => trips[i])`), never over the raw `trips` parameter, so a
   caller passing a superset in `trips` with a subset in `order` cannot anchor
   the timeline to a window belonging to a trip outside the candidate. The
   generator's logout windows are office-departure
   slots, so that start correctly denotes gate departure on an outbound run. The
   field keeps its Plan 1 name; its doc comment in `core/types.ts` says which
   it means.
5. `perPassengerAddedMin[employeeId]` = that rider's OWN in-vehicle duration in
   this candidate, minus `soloMinutes` for their trip. Their in-vehicle duration
   is (elapsed time at the stop where they leave the vehicle) − (elapsed time at
   the stop where they board it): inbound they board at their home stop and
   leave at their gate; outbound they board at their gate and leave at their home
   stop. **Never negative — clamp at 0.**
   Do NOT read this as "elapsed to office minus solo": every inbound rider
   reaches the gate at the SAME elapsed time, so that reading makes the
   differences depend only on differing `soloMinutes`, and since the
   first-picked-up rider is typically the farthest it hands them the SMALLEST
   detour — the exact inverse of test case 5 below. Accumulate elapsed minutes
   RELATIVE to the start and add the epoch base once at the end; subtracting two
   `start + small` values at epoch-ms magnitude (~1.76e12) loses the exact zero
   that case 1 requires to floating-point cancellation.
   **The base is epoch MILLISECONDS and the accumulator is MINUTES — multiply
   by 60_000 when you add it back.** An earlier draft of this bullet said only
   "add the epoch base once at the end", and that omission shipped a real bug:
   `start + elapsedMinutes` advanced a timestamp by 20 ms for 20 minutes of
   travel, and the already-merged `time-window` policy — which reads
   `pickupTimes` and converts correctly — then reported a 45-minute SLA
   violation on a candidate whose real pickup time was fine. It passed CI
   because no test asserted on the field's value at all. Any relative-minutes
   accumulator added back to an epoch-ms base needs this conversion stated
   explicitly, and a test asserting the resulting VALUE, not just its presence.
6. `gateIds` = distinct gates in visit order.
7. `seatsUsed` = Σ trip seats.

**Test cases** (all against Plan 1's `tests/helpers/world.ts`):

| # | Case | Expect |
|---|---|---|
| 1 | single trip, order [0] | `km` == solo route km; `perPassengerAddedMin` all 0 |
| 1b | logout, single trip | `perPassengerAddedMin` exactly 0, not an epsilon |
| 5b | logout, two trips | the **LAST-dropped** rider has the larger added minutes; must FAIL if the login ordering is applied |
| 8 | logout `km` | equals the gate->drop->drop sum, and is NOT equal to the login-sequence sum for the same trips |
| 9 | mixed directions in one `order` | throws, naming both directions |
| 2 | two trips same gate | `gateIds.length` == 1 |
| 3 | two trips different gates | `gateIds.length` == 2, in visit order |
| 4 | two trips, boarding split | `minutes` includes `boardingMinutes(1 or 2, 2)`, not `2 × boardingMinutes(1,1)` |
| 5 | first-picked-up passenger | has the LARGER added minutes (rides longest) |
| 6 | `buildCandidate` called twice, same args | deep-equal (determinism) |
| 7 | input `trips` array | not mutated |

---

### Task 2: `solvers/pickup-order.ts` — exact ordering at n ≤ 4 (A5)

**Files:** `src/solvers/pickup-order.ts`, `tests/solvers/pickup-order.test.ts`

**Produces:** `MAX_EXACT_PICKUPS` (6), `permutations<T>(xs: T[]): T[][]`,
`bestPickupOrder(stops: LatLng[], office: LatLng, d: (a: LatLng, b: LatLng) => number, direction: Direction): { order: number[]; strategy: 'exact' | 'nearest-neighbour' }`

Returns **indices**, not points, so the caller can map back to trips.

**The objective is direction-dependent — do not omit the `direction`
parameter.** The office is the route's LAST stop inbound and its FIRST stop
outbound, so the two cost functions are:

- `login`:  `Σ inner legs + d(stops[last], office)`
- `logout`: `d(office, stops[first]) + Σ inner legs`

Under a symmetric `d` these two have the same minimum *value* — reversing a
permutation maps one objective onto the other — so a direction-blind
implementation still returns a correct total km while returning the drop order
**mirrored**. That is not harmless: outbound, the rider dropped first has the
shortest ride, so a mirrored order hands the short ride to the wrong person,
redistributes `perPassengerAddedMin`, and can push a specific rider past
`detour-fairness` or out of their window. Under the asymmetric route cache the
km diverges as well. Same root cause as the `buildCandidate` contract above.

```ts
export const MAX_EXACT_PICKUPS = 6   // 720 perms; 12-seat shuttles must NOT use this

export function bestPickupOrder(pickups, office, d, direction) {
  const n = pickups.length
  if (n <= 1) return { order: pickups.map((_, i) => i), strategy: 'exact' }
  if (n > MAX_EXACT_PICKUPS) {
    return { order: nearestNeighbourOrder(pickups, office, d, direction), strategy: 'nearest-neighbour' }
  }
  let best: number[] = [], bestKm = Infinity
  for (const perm of permutations(pickups.map((_, i) => i))) {
    let km = 0
    for (let i = 1; i < perm.length; i++) km += d(pickups[perm[i - 1]!]!, pickups[perm[i]!]!)
    km += direction === 'logout'
      ? d(office, pickups[perm[0]!]!)      // outbound: office is the FIRST stop
      : d(pickups[perm[perm.length - 1]!]!, office)  // inbound: office is LAST
    if (km < bestKm) { bestKm = km; best = perm }
  }
  return { order: best, strategy: 'exact' }
}
```

**Test cases:**

| # | Case | Expect |
|---|---|---|
| 1 | n=1 | `[0]` |
| 2 | n=2, one clearly nearer the office | the far one first |
| 3 | n=3 collinear away from office, `login` | strictly descending distance-to-office |
| 3b | the same three stops as `logout` | strictly ASCENDING distance-to-office — the exact mirror of case 3, and it must FAIL if `direction` is ignored |
| 4 | n=4 | result is a permutation of 0..3, and no other permutation is cheaper (brute-force cross-check in the test) |
| 5 | `permutations([1,2,3])` | 6 arrays, all distinct |
| 6 | `permutations` of 4 items | 24 |
| 7 | n=7 | falls back — assert the **strategy marker**, not wall-clock |
| 8 | 12-seat shuttle case n=8 | falls back, returns a valid permutation |

Case 4 is the important one: the test **independently** enumerates all 24
orders and asserts `bestPickupOrder`'s answer ties the minimum. That is what
makes "exact, not approximated" a verified claim rather than a slogan.

`nearestNeighbourOrder` is direction-aware for the same reason: inbound it
grows the chain toward the office, outbound it grows outward FROM the office.

**No wall-clock assertions.** `strategy` is `'exact' | 'nearest-neighbour'`,
and the tests assert the strategy at n=6 vs n=7. Timing
in a test is machine- and load-dependent, and what we actually care about is
which code path ran.

---

### Task 3: `solvers/corridor.ts` — H3 corridor index and prefix scan (A8)

**Files:** `src/solvers/corridor.ts`, `tests/solvers/corridor.test.ts`

**Produces:** `H3_RES` (8), `corridorCells(polyline: LatLng[]): string[]`,
`corridorKey(cells: string[], direction: Direction): string`,
`buildCorridorIndex(entries: Array<{ id: string; key: string }>): string[]`,
`prefixRange(index: string[], prefix: string): string[]`,
`corridorCandidates(tripId: string, index: string[], key: string): string[]`

Mechanism (spec 01 §5–§6):
1. `corridorCells` — map each polyline point through `latLngToCell(lat, lng, 8)`,
   de-duplicate, then close gaps with `gridPathCells` so the corridor is
   contiguous. **Without gap-filling two cabs on the same road can produce
   non-overlapping cell sets and the whole technique silently fails.**
2. `corridorKey` — join the cells into one string. **Reverse the sequence for
   `login`** (many homes → one office converge, so they share a *suffix*;
   reversing makes it a prefix). Leave `logout` unreversed.
3. Index = sorted `"<key>::<tripId>"` array. Candidate lookup = binary-search
   prefix range. O(log n), no Redis.

**Test cases:**

| # | Case | Expect |
|---|---|---|
| 1 | `corridorCells` on a 2-point line | contiguous cells, `gridPathCells` filled |
| 2 | all cells are res-8 | `getResolution(c) === 8` for every cell |
| 3 | two login trips converging on one office | share a non-empty key prefix |
| 4 | the same two trips as `logout` | prefix NOT shared (proves the reversal matters) |
| 5 | `prefixRange` | returns exactly the entries with that prefix |
| 6 | `prefixRange` with no match | `[]` |
| 7 | `corridorCandidates` | excludes the querying trip itself |
| 8 | 200 fixture trips indexed | correctness only — **no timing assertion** |

Case 4 is the one that proves the design's central adaptation is real rather
than asserted — and it is now backed by measurement: two homes converging on a
Bellandur office share **8** leading cells keyed reversed for login and **0**
keyed as-is. Pin those two counts in the test, not merely "shared / not shared".

---

### Task 4: `solvers/pool-merger.ts` — Clarke-Wright savings (the floor)

**Files:** `src/solvers/pool-merger.ts`, `tests/solvers/pool-merger.test.ts`

**Produces:** `savings(i, j, officeAt, d): number`, `poolMerger: Solver`

```ts
/** Convergent Clarke-Wright: pooling saves the LONGER solo haul minus the connector. */
export function savings(i: LatLng, j: LatLng, office: LatLng, d: Dist): number {
  return Math.max(d(i, office), d(j, office)) - d(i, j)
}
```

Algorithm:
1. Group trips by `(officeId, direction, overlapping window)`.
2. Within a group, use `corridorCandidates` to shortlist pairs (not all-pairs).
3. Score every chain-endpoint pair with `savings`, sort descending.
4. Greedily merge while `evaluate(...).blocked === false` and capacity holds;
   re-order each merged chain with `bestPickupOrder(stops, office, d, direction)`
   — it returns `{ order, strategy }`, not a bare array, and the group's own
   `direction` from step 1 is what you pass; re-evaluate endpoints after each
   merge so 3- and 4-seat fills form.
5. Emit a `Proposal` per merge **and per refusal**, each carrying its trace.

**Test cases:**

| # | Case | Expect |
|---|---|---|
| 1 | `savings` formula | equals `max(d(i,O), d(j,O)) − d(i,j)` on hand-worked numbers |
| 2 | two adjacent pickups, same office/window | one merge proposed, `savings.km > 0` |
| 3 | two pickups 30 km apart | no merge (negative savings) |
| 4 | four adjacent 1-seat trips, 4-seat cab | a single 4-passenger chain, not two pairs |
| 5 | five adjacent trips, 4-seat cab | at most 4 in any proposal |
| 6 | a merge that trips `gender-safety` | proposal emitted with `trace.blocked === true`, NOT silently dropped |
| 7 | golden: 200 fixture trips | `diff.cabKm` — **measure, then pin** (see below) |
| 8 | golden: 200 fixture trips | `solved.vehiclesUsed < baseline.vehiclesUsed` |
| 9 | run twice on the same input | identical result (determinism) |
| 10 | `input.trips` | not mutated |

Case 6 is the demo's most memorable beat and must be a test, not a hope.

**Golden thresholds are measured, never guessed.** Land case 7 in two steps:
first assert `toBeGreaterThan(0)` and log the real value; once green, pin at
~80% of what you measured and record it in a comment
(`// measured 47.3 km on the committed fixture, seed 20260905`). The "≥30 km"
figure in earlier drafts was invented. A threshold nobody measured either
asserts nothing or fails and invites someone to lower it to match — both turn a
golden test into decoration.

**Prove each guard by breaking it.** Before committing, temporarily break the
behaviour the guard names, confirm the guard FAILS, restore, and report that it
did. Task 1 and Task 2 of Plan 1 each shipped a guard that did not guard what
its name claimed; this step is what catches that. Applies here to case 6 (a
policy-blocked proposal must still be emitted, not dropped).

---

### Task 5: `solvers/metro-feeder.ts` — semi-on-demand feeder (the swing)

**`FLOOR_SEATS` — ALREADY FIXED, do not redo it.** Landed in Task 1 as commit
`327ac7f`: `computeMetrics` now derives the floor unit from the largest capacity
in `w.vehicles` instead of a hard-coded 4, so the bound moved from 50 to 17 over
the committed 200-trip fixture. Verify it still holds once this solver's
shuttles are in play — the check is `theoreticalFloorVehicles <= vehiclesUsed`
on the golden run — but do not change `scenario.ts` again. The original note,
kept for the reasoning: `scenario.ts` hard-coded the fleet-floor unit at 4 seats. That is right while the fleet is cab-dominated, but
this solver pools feeder legs onto **12-seat shuttles**, and `ceil(pax/4)` is
larger than `ceil(pax/12)` — so the "theoretical floor" would claim more
vehicles are needed than actually are, and can exceed the achieved
`vehiclesUsed`, inverting the headline comparison. Compute the floor against the
largest vehicle capacity actually in play, or per vehicle class, before this
solver's golden metrics are trusted.

**Files:** `src/solvers/metro-feeder.ts`, `tests/solvers/metro-feeder.test.ts`

**Produces:** `FEEDER_RADIUS_KM` (6), `LAST_MILE_RADIUS_KM` (3),
`MAX_EXTRA_MIN` (15), `MIN_KM_SAVED` (2), `metroFeeder: Solver`

Algorithm (spec §10.1):
1. For each trip: `directKm/directMin` from the route provider.
2. **Direction-aware station shortlisting.** A rider boards the metro on the
   side they start from, so the two radii attach to the HOME side and the
   OFFICE side, never to a fixed leg index:
   - `login`:  boarding = `nearestN(pickup, stations, 3, FEEDER_RADIUS_KM)`,
     alighting = `nearestN(officeGate, stations, 3, LAST_MILE_RADIUS_KM)`
   - `logout`: boarding = `nearestN(officeGate, stations, 3, LAST_MILE_RADIUS_KM)`,
     alighting = `nearestN(pickup, stations, 3, FEEDER_RADIUS_KM)`

   Because `FEEDER_RADIUS_KM` (6) and `LAST_MILE_RADIUS_KM` (3) differ, getting
   this backwards does not merely mirror the route — it shortlists the wrong
   stations entirely and silently drops feasible outbound feeders. 67 of the 200
   fixture trips are `logout`. Same root cause as the `buildCandidate` and
   `bestPickupOrder` contracts above.
3. For each (b, a): `metroLegMinutes(findMetroPath(b, a, mg), headway)`; total =
   feeder + metro + last mile. `cabKmSaved = directKm − feederKm − lastMileKm`.
4. Accept if `total <= directMin + MAX_EXTRA_MIN` **and**
   `cabKmSaved >= MIN_KM_SAVED`; keep the best (b, a) by `cabKmSaved`.
5. **Compose:** group accepted feeder legs by `(boardingStation, 10-min bucket)`
   and run `poolMerger` over them so feeders are shared shuttles, not solo cabs.
6. Policy-gate each shuttle group (`seat-capacity` now sees 12 seats).

**Test cases:**

| # | Case | Expect |
|---|---|---|
| 1 | trip with no station within 6 km | no feeder proposal |
| 1b | a `logout` trip whose OFFICE is within 3 km of a station but whose home is 5 km from one | feeder proposed — must FAIL if the login radii are applied outbound |
| 2 | Electronic City trip near ELCT | feeder proposed, `cabKmSaved >= 2` |
| 3 | a trip whose metro detour exceeds +15 min | rejected on time, not on distance |
| 4 | a trip already 1 km from its office | rejected on `MIN_KM_SAVED` |
| 5 | cross-line trip (Purple → Yellow) | path has 2 interchanges, penalty applied |
| 6 | three trips to the same station in one bucket | ONE shuttle proposal, not three (the composition) |
| 7 | golden: 200 fixture trips | `metroPaxKm > 0` and `diff.cabKm > 0` |
| 8 | metro leg carbon | uses `co2MetroPerPassengerKm`, not the cab factor |
| 9 | determinism | identical across two runs |

Case 6 is the elegant bit and the headline claim ("we deleted N% of cab-km").

---

## Definition of done for Plan 2

```bash
cd commute-os && npm run typecheck && npm test
```

Both solvers registered, ~60 new tests, boundary test extended, and the two
golden fixtures pinned at ~80% of their MEASURED values with the measurement
recorded in a comment. (An earlier draft of this line asserted "≥30 km saved";
that figure was invented, and Task 4's own "golden thresholds are measured,
never guessed" rule governs. A definition of done must not contradict the task
it closes.)

## Explicitly NOT in Plan 2 (Tier B/C)

Insertion heuristic for Approve/Revert (B2) · two-tier SLA (B3) · commitment
window (B4) · skills-based matching (B1) · Alonso-Mora · any live solver.
