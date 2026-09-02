# 01 — smart-aiport-cabpooling-backend

**Reuse: 🟢 HIGH — the best algorithm in the reference set.**
`github.com/maheshwarisharman/smart-aiport-cabpooling-backend` · TypeScript/Bun ·
43 files · last commit 2026-02-18 (actively maintained)

## What it actually is

A real, working airport→city cab-pooling backend. Express + Bun, Prisma/Postgres,
Redis, `h3-js`, worker threads, Docker Compose, OpenAPI spec. The PRD's claim
("H3 geo-indexing + Redis + matching worker") is **accurate** — this is the one
repo that delivers what was advertised.

Domain: passengers land at **one airport** and disperse to **many destinations**
— a *divergent* problem. Your problem is *convergent* (many homes → one office).
That difference matters and is handled in §4.

## 2. Layout

```
index.ts                            Express bootstrap
prisma/schema.prisma                Users, Drivers, Cabs, Trips, RideRequests
src/rideMatching/h3Indexing.ts      route → H3 cell sequence          ★
src/utils/redisCaching.ts           THE matching algorithm            ★★★
src/utils/pubsub.ts                 Redis pub/sub fan-out
src/workers/rideMatchingWorker.ts   worker thread wrapper
src/workers/workerPool.ts           pool manager
src/routes/{findRide,startRide,cancelRide,signup}.ts
```

★ = worth reading · ★★★ = read this

## 3. The core idea (`src/utils/redisCaching.ts:130`)

`matchUserWithAvaialbleTrip(user_id, routeIndexes, userMetaData)` — note the
typo in the method name, it's theirs.

**The trick:**

1. A route is a list of H3 cells: `['8828…a1','8828…a3','8828…b7', …]`
2. Concatenate into one string. H3 indexes are **fixed 15 chars**, so the string
   is a clean fixed-stride array: `getRouteString(routeIndexes)`
3. Store as `"<routeString>::<userId>"` in a Redis **lexicographic sorted set**
4. Two routes sharing a road corridor now share a **string prefix**

Matching then becomes three range scans:

| Step | Question | Redis op |
|---|---|---|
| 1a | Is my route a **subset** of someone's longer route? | `ZRANGEBYLEX [myRoute → [myRoute\xff` |
| 1b | Is someone's route a subset of **mine**? | scan neighbours, `myRoute.startsWith(theirs)` |
| 2 | Otherwise, who's the **cheapest detour**? | `ZRANGEBYLEX` ± 5 either side, then split-point maths |

Step 2 finds the **longest common prefix** by stepping 15 chars at a time until
the H3 cells diverge:

```ts
for (let i = 0; i < minLen; i += 15) {
  if (mine.substring(i,i+15) !== theirs.substring(i,i+15)) break;
  splitIndex = i + 15;
}
```

`splitIndex === 0` → routes diverge at the airport gate → not poolable, skip.
Otherwise the cell at `splitIndex-15` is the **split point**: where the shared
corridor ends and the detour begins. Detour cost is then measured from there.

**Why this is clever:** "find me a poolable route" — normally a geometric
problem needing an R-tree or repeated distance matrices — becomes a *substring*
problem answered by one sorted-set range scan. O(log n) instead of O(n²).

## 4. Adapting it to commute-os (the inversion)

Airport = divergent: all routes start at the same place → shared **prefix**.
Employee login = convergent: all routes end at the same office → shared
**suffix** (the common approach corridor into the office).

**Fix: reverse the H3 sequence before stringifying.** A shared suffix becomes a
shared prefix and every scan above works untouched. For logout trips (office →
homes) the problem is genuinely divergent, so don't reverse. One boolean.

```ts
const key = direction === 'login'
  ? cells.slice().reverse().join('')   // convergent → reverse
  : cells.join('')                     // divergent  → as-is
```

**Drop Redis.** For 200 trips, `array.sort()` + binary search for the prefix
range is the same complexity, zero infrastructure, and works in a Next.js route
handler. Redis earns its place at 100k concurrent requests, not 200 fixtures.

## 5. Also worth taking

- **`h3Indexing.ts:11`** — `H3_RESOLUTION = 8`, commented "~0.7km hexagon width
  (good for urban areas)". A researched default; adopt it for zone bucketing.
- **`h3Indexing.ts:92`** — `fillRouteGaps()` uses `gridPathCells` to interpolate
  between sparse polyline points so a corridor has no holes. You need exactly
  this if you build corridor keys from cached polylines.
- **`prisma/schema.prisma`** — `Trips` vs `RideRequests` split is a clean
  separation: a request is demand, a trip is committed supply. Mirrors the
  `Proposal` → approved-`Trip` transition in the commute-os design.

## 6. What to ignore

Redis client/pub-sub/caching layer, `workers/*` (Bun worker threads),
Prisma + migrations, Docker Compose, auth/OTP/signup, `openapi.yaml`. All
production-correct and all dead weight in a 14-hour demo. Their
`fetchRouteFromGoogle` (`h3Indexing.ts:16`) is also the exact live-API
dependency the commute-os design deliberately avoids — read it, don't adopt it.

## 7. Verdict

Take **one idea** — the reversed-suffix prefix scan for corridor candidates —
and implement it in ~40 lines inside `solvers/pool-merger.ts`. That single
technique gives you a defensible answer to *"how do you find candidates at
scale?"*: **"H3 corridor keys in a sorted index, O(log n) prefix scan, not an
O(n²) distance matrix."** Judges will ask. This is the answer.
