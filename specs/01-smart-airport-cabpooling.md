# 01 — smart-aiport-cabpooling-backend · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/maheshwarisharman/smart-aiport-cabpooling-backend` |
| **Reuse** | 🟢 **HIGH** — the best algorithm in the reference set |
| **Stack** | TypeScript · Bun runtime · Express · Prisma/PostgreSQL · Redis · `h3-js` |
| **Size** | 1.8 MB · 43 files · 16 `.ts` |
| **Activity** | last commit 2026-02-18 (actively developed) |
| **Licence** | none declared — **read for ideas, don't copy verbatim** |
| **Local** | `reference/smart-aiport-cabpooling-backend/` |

> Note: "aiport" is misspelled in the repo name, and `matchUserWithAvaialbleTrip`
> is misspelled in the source. Both are theirs; preserved here so greps match.

---

## 1. Domain & problem shape

Airport → city cab pooling. Passengers land at **one fixed origin** (hardcoded
Delhi: `28.5562, 77.1000`, `h3Indexing.ts:7`) and disperse to **many
destinations**.

This is a **divergent** routing problem: all routes share a common start and
fan out. Employee login commute is the mirror image — **convergent**: many
homes, one office. That distinction drives the one adaptation you must make
(§6).

Matching is **online and incremental**: a request arrives, gets matched against
a live pool immediately, and either joins a trip or waits in the pool. It is not
a batch solver.

---

## 2. Architecture

```
index.ts                              Express bootstrap, route mounting
prisma/schema.prisma                  5 models (§3)
prisma/migrations/                    5 migrations, 2026-02-17
src/routes/
  ├─ signup.ts                        auth + OTP
  ├─ findRide.ts                      POST — enter the matching pool
  ├─ startRide.ts                     driver starts trip, OTP verify
  └─ cancelRide.ts                    leave pool / leave trip
src/rideMatching/h3Indexing.ts        route → H3 cell sequence          ★
src/utils/
  ├─ redisCaching.ts                  RedisPoolingService — THE algorithm  ★★★
  ├─ redisClient.ts                   connection factory
  ├─ pubsub.ts                        Redis pub/sub for match notifications
  └─ sampleDataSet.ts                 fixtures
src/workers/
  ├─ rideMatchingWorker.ts            Bun Worker wrapper (95 lines)
  └─ workerPool.ts                    pool manager
lib/prisma.ts                         Prisma singleton
openapi.yaml · docker-compose.yml · Dockerfile
```

**Concurrency model:** the main thread receives HTTP, then posts
`MATCH_RIDE` / `REMOVE_USER` / `REMOVE_USER_FROM_TRIP` messages to a Bun worker
pool. Each worker holds **its own** Redis + PubSub + Prisma connections
(`rideMatchingWorker.ts:16-28`) to avoid main-thread contention. Matching is
treated as CPU-bound, which it is once the candidate set is fetched.

---

## 3. Data model (`prisma/schema.prisma`)

```
Users        id, name, email, password, gender, age, ride_otp, otp_expiry
Drivers      id, name, email, password, gender, age  ──1:1──> Cabs
Cabs         id, cab_number, cab_type, no_of_seats, luggage_capacity,
             status(default AVAILABLE), driver_id
Trips        id, status, fare_each, no_of_passengers, total_luggage, cab_id
RideRequests id, status, no_of_passengers, luggage_capacity, issued_price,
             joined_at, user_id, trip_id
```

**The `Trips` vs `RideRequests` split is the modelling lesson.** A
`RideRequest` is *demand* — what one user wants. A `Trip` is *committed supply*
— a cab with an aggregated passenger set. They're separate tables with separate
lifecycles, joined many-to-one.

This maps directly onto the commute-os design's `Proposal` → approved-`Trip`
transition (design §8). Their `RideRequests.status` is the same state machine as
`Proposal.status`.

Also note `Cabs.luggage_capacity` alongside `no_of_seats` — capacity is
**multi-dimensional**, matching PyVRP's vector `capacity` (see spec 05 §4).

---

## 4. Redis key design — read this before the algorithm

Three key patterns, and the details matter:

| Key | Type | Contents |
|---|---|---|
| `h3:airport_pool` | **sorted set** | `"<routeString>::<userId>"` and `"<routeString>::TRIP<uuid>"` |
| `<userId>` | string (JSON) | `PassengerMetaData` |
| `TRIP<uuid>` | string (JSON) | `TripMetaData` |

**The critical implementation detail** (`redisCaching.ts:storeRouteH3Index`):

```ts
await this.client.zAdd(this.POOL_KEY, [{ score: 0, value: memberValue }]);
```

**Every member is stored with `score: 0`.** Redis only orders a sorted set
lexicographically when all scores are equal — `ZRANGEBYLEX` is undefined
behaviour otherwise. The score field is deliberately unused; the sorted set is
being abused as a **lexicographically ordered index**. Miss this and a
reimplementation silently returns garbage.

Waiting passengers and formed trips live in the *same* index, distinguished only
by the `TRIP` prefix in the id half of the member string.

---

## 5. The algorithm (`src/utils/redisCaching.ts:130`)

`matchUserWithAvaialbleTrip(user_id, routeIndexes, userMetaData): RouteMatch`

### 5.1 Route encoding

1. A route becomes an ordered list of H3 cells at **resolution 8** (≈0.7 km
   hexagon edge — `h3Indexing.ts:11`, commented "good for urban areas").
2. Cells are concatenated with no separator: `routeIndexes.join('')`.
3. H3 indexes are **fixed 15 characters**, so the concatenation is a
   fixed-stride array addressable by `substring(i, i+15)`.
4. Stored as `"<routeString>::<userId>"`.

Two routes travelling the same corridor out of the airport therefore share a
**string prefix**, character for character.

### 5.2 Route construction (`h3Indexing.ts:119`)

`generateH3IndexesForRoute(destination, apiKey, options)`:

1. `latLngToCell(dest.lat, dest.lng, 8)` → destination cell
2. Google Routes API `computeRoutes`, field-masked to
   `routes.legs.steps.startLocation,endLocation`
3. Map every step endpoint through `latLngToCell`
4. De-duplicate (`new Set`)
5. **`fillRouteGaps()`** (`:92`) — Google step endpoints are sparse, so
   consecutive cells may not be adjacent. `gridPathCells(start, end)` walks the
   hex grid between them, guaranteeing a contiguous corridor. **Without this the
   prefix trick breaks**, because two vehicles on the same road can produce
   non-overlapping cell sets.
6. Force-append the destination cell if absent

Returns `{ destinationH3, pathH3Indexes, totalHexagons }`.

### 5.3 Matching — three checks in order

**Step 1a — am I a subset of a longer route?**

```ts
zRange(POOL_KEY, `[${myRouteString}`, `[${myRouteString}\xff`,
       { BY: 'LEX', LIMIT: { offset: 0, count: 5 } })
```

`\xff` as the upper bound is the standard prefix-scan idiom: every member
beginning with `myRouteString` sorts inside that range. A hit means someone is
driving my entire route and continuing further — a **perfect** pool, zero
detour. Returns `match_type: 'DIRECT'`.

**Step 1b — is someone a subset of me?**

Fetch 5 lexicographic predecessors and 5 successors, then test
`myRouteString.startsWith(neighborRoute)`. Also `DIRECT` — I drive their whole
route and continue.

**Step 2 — cheapest detour (`:212`)**

For each of the 10 neighbours, find the **longest common prefix** by stepping
one whole H3 cell at a time:

```ts
let splitIndex = 0;
const minLen = Math.min(myRouteString.length, candidateRouteString.length);
for (let i = 0; i < minLen; i += 15) {
  if (myRouteString.substring(i,i+15) !== candidateRouteString.substring(i,i+15)) break;
  splitIndex = i + 15;
}
if (splitIndex === 0) continue;   // diverge at the airport gate — unpoolable
```

Then:

```ts
const splitPointH3   = myRouteString.substring(splitIndex - 15, splitIndex);
const candidateDestH3 = candidateRouteString.slice(-15);
const detourMeters = await this.fetchRouteDistance(
  cellToLatLng(splitPointH3), cellToLatLng(candidateDestH3));
if (detourMeters < 3000 && detourMeters < minDetourMeters) { /* accept */ }
```

The split point is where the shared corridor ends. Detour cost is the driving
distance from there to the candidate's destination — **the unique arm of the
Y-split**. Threshold is a hardcoded **3000 m** (`:239`).

**Complexity:** `O(log n)` for the range scans plus `O(1)` string comparisons on
a capped 10-candidate set, versus `O(n²)` for an all-pairs distance matrix. The
geometry is answered by string operations; Google is called only for the ≤10
survivors.

### 5.4 Constraint check (`checkMatchConstraints`)

```ts
LUGGAGE_CAPACITY = 4        // redisCaching.ts:50
MAX_PASSENGERS   = 3        // redisCaching.ts:51
```

Rejects if either sum would exceed capacity. On acceptance:

1. `zRem` both route signatures from the pool
2. `del` both users' metadata keys
3. mint `tripKey = "TRIP" + randomUUID()`
4. if the trip is **not** full, `storeTripRoute(...)` puts the merged route back
   into the pool so a third passenger can still join
5. build `TripMetaData` with the aggregated passenger set

Two cases, distinguished by `'users' in data`: two individuals matching, versus
a new user joining an existing trip.

### 5.5 Pricing

```ts
const MATCH_DISCOUNT = 0.7        // 30% off
```

Applied per user via `Math.ceil(issued_price * 0.7)`. When two individuals
match, **both** are discounted; when someone joins an existing trip, **only the
joiner** is — existing prices are already committed. A defensible fairness rule,
and a real design decision worth borrowing: *savings go to whoever is asked to
accept a change.*

---

## 6. Adapting to commute-os — the inversion

Airport = divergent → routes share a **prefix**.
Employee login = convergent → routes share a **suffix** (the common approach
corridor into the office).

A prefix scan finds nothing useful on convergent routes. **Reverse the cell
sequence before stringifying** and a shared suffix becomes a shared prefix, so
every scan in §5.3 works untouched:

```ts
// core/corridor.ts
// PURPOSE: build the lexicographic corridor key for a trip.
// PIVOT: login trips converge on the office -> reverse. Logout trips diverge -> don't.
export function corridorKey(cells: string[], direction: Direction): string {
  return direction === 'login'
    ? cells.slice().reverse().join('')   // convergent
    : cells.join('')                     // divergent
}
```

Logout trips (office → many homes) are genuinely divergent, so they use the
unreversed form. One boolean, keyed on `Trip.direction`.

**Drop Redis entirely.** For 200 trips a sorted array plus binary search gives
identical asymptotics with no infrastructure:

```ts
// solvers/corridor-index.ts
const index = trips.map(t => `${corridorKey(cells(t), t.direction)}::${t.id}`).sort()
function prefixRange(index: string[], prefix: string): string[] {
  const lo = lowerBound(index, prefix)                 // binary search
  const out = []
  for (let i = lo; i < index.length && index[i].startsWith(prefix); i++) out.push(index[i])
  return out
}
```

Redis earns its place at 100k concurrent requests. At 200 fixtures it is a
process to start, a connection to fail, and a demo to lose.

**Replace their Google call** with the design's `routing.ts` cache
(cache → ORS → haversine×1.3). Their split-point detour measurement becomes a
cache lookup, so the whole matcher runs offline and deterministically.

---

## 7. Bugs and rough edges found

Worth knowing before you copy anything:

1. **Step 1a doesn't exclude formed trips.** Step 2 filters
   `!c.includes('TRIP')`, but the Step 1a superset scan filters only
   `!c.includes(user_id)`. A `TRIP` member can therefore be returned as a
   `perfectLongMatch` and passed to `checkMatchConstraints` as if it were a
   user. It partly works because trip metadata is shaped compatibly, but the
   asymmetry looks unintentional.
2. **`user_id` matched by substring.** `c.includes(user_id)` on the whole
   member string; a UUID could in principle collide with the route portion.
   Should split on `::` first.
3. **Google failure returns `9999999` metres** (`fetchRouteDistance` catch), so
   a failed API call silently excludes that candidate rather than erroring.
   Fail-closed and reasonable — but a Google outage degrades matching to zero
   with no signal.
4. **Hardcoded constants** — `3000` m detour, `0.7` discount, resolution `8`,
   Delhi airport coordinates, `count: 5` neighbours. All should be config.
5. **`h3Indexing.ts` is untyped JS in a `.ts` file** — no annotations on
   `fetchRouteFromGoogle`, `fillRouteGaps`, `generateH3IndexesForRoute`.
6. **No tests anywhere in the repo.**

---

## 8. What to take, precisely

| Take | From | Effort |
|---|---|---|
| Reversed-suffix corridor key + prefix scan | `redisCaching.ts:130` | ~40 lines |
| `fillRouteGaps` via `gridPathCells` | `h3Indexing.ts:92` | ~15 lines |
| H3 resolution 8 for urban zone bucketing | `h3Indexing.ts:11` | one constant |
| Split-point detour measurement | `redisCaching.ts:212-240` | ~20 lines |
| Demand/supply table split | `schema.prisma` | design only |
| "Discount whoever accepts the change" | `MATCH_DISCOUNT` | design only |
| Partial-trip re-pooling (rejoin pool unless full) | `checkMatchConstraints` | ~10 lines |

**Ignore:** Redis client, pub/sub, worker pool, Prisma + migrations, Docker,
auth/OTP, `openapi.yaml`, all Google calls.

---

## 9. The judge answer this earns you

> *"How do you find pooling candidates at scale?"*
>
> "We encode each route as a sequence of H3 cells at resolution 8 and
> concatenate them into a corridor key. Trips sharing a corridor share a string
> prefix, so candidate lookup is a binary search over a sorted index —
> O(log n) — instead of an O(n²) distance matrix. We reverse the key for login
> trips because employee commutes converge on the office rather than diverging
> from it, so the shared segment is a suffix. Distance is only computed for the
> handful of candidates that survive the prefix scan."

That is a real systems answer, and it comes almost entirely from one file.
