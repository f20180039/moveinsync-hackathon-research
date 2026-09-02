# Reference Repo Index — MoveInSync Hackathon

Five repos cloned to `../reference/` (shallow, git-ignored). Surveyed 2026-09-02.
This file is the **router**: read it, pick the one spec you need, ignore the rest.

## Verdict table

| # | Repo | Claimed | **Actually is** | Reuse | Spec |
|---|---|---|---|---|---|
| 1 | `smart-aiport-cabpooling-backend` | H3 + Redis + matching worker | ✅ **True.** Working TS backend, real matching algorithm | 🟢 **HIGH** | [01](01-smart-airport-cabpooling.md) |
| 2 | `RideShare-Optimizer` | BFS, Prim's, TSP | ✅ **True.** One 1186-line Streamlit file, all three implemented | 🟢 **HIGH** | [02](02-rideshare-optimizer.md) |
| 3 | `Car-Pooling-System` | Auth + ride matching + Maps | ⚠️ **Half.** MERN CRUD works; **matching is commented out** | 🟡 **LOW-MED** | [03](03-car-pooling-mern.md) |
| 4 | `Carpool_Management_System` | Real-time tracking + optimal allocation | ❌ **False.** Zero distance/allocation code. Leaflet + Firebase + chat | 🔴 **LOW** | [04](04-carpool-management.md) |
| 5 | `rideAndMove` | Routing + Admin Panel + CDK | ❌ **False.** 6 markdown files, **no code**. `datamodel.md` is 0 bytes | 🔴 **NONE** | [05](05-rideandmove.md) |

**Bottom line:** two of the five are worth your time. Repos 4 and 5 were mis-sold
in the PRD — don't budget hours for them.

## If you only read one thing

**The single best idea across all five repos** is in #1: encode a route as a
concatenated string of H3 cell indexes, store it in a lexicographically-sorted
set, and find poolable routes with a **prefix range scan**. Longest common
prefix = the split point = where the detour begins. It turns "find me a
shareable route" into a substring problem.

`reference/smart-aiport-cabpooling-backend/src/utils/redisCaching.ts:130`

**For commute-os this needs one inversion.** The airport case is *divergent*
(one origin, many destinations) so routes share a **prefix**. Employee login
transport is *convergent* (many pickups, one office) so routes share a
**suffix** — the common approach into the office. Reverse the H3 string and the
same prefix scan works unchanged.

And you don't need Redis: a sorted in-memory array + binary search gives the
same complexity for 200 trips.

## Reuse map → commute-os

| commute-os module | Take from | What |
|---|---|---|
| `core/geo.ts` | #3 `rideRequestController.js:61-75` | Haversine (commented but correct) |
| `core/geo.ts` — zone bucketing | #1 `h3Indexing.ts:11` | H3 res 8 ≈ 0.7 km hex — good urban default |
| `solvers/pool-merger.ts` — corridor candidates | #1 `redisCaching.ts:130` | Reversed-suffix prefix scan |
| `solvers/pool-merger.ts` — pickup order | #2 `app.py:352` | Multi-start nearest-neighbour → **replace with brute force, see below** |
| `solvers/metro-feeder.ts` — route gap filling | #1 `h3Indexing.ts:92` | Interpolating cells between sparse route points |
| `core/policies/gender-safety.ts` | #3 `rideSchema.js:13-17` | `preferences.femaleOnly` flag precedent |
| `ui/SuggestionFeed.tsx` — confidence badge | #3 `rideRequestController.js:37-42` | Match-% banding table (100/75/50/0%) |
| `core/routing.ts` fallback | #2 `app.py:80` | OpenRouteService as a keyless-ish alternative to Google |

## Two corrections to make when lifting

1. **Don't copy #2's pickup ordering.** `find_optimal_pickup_order` is
   multi-start nearest-neighbour at O(n³). A cab seats 4. With n≤4 pickups
   there are at most 4! = 24 permutations — **brute-force it and be exact**,
   in microseconds. Their `TSPSolver` branch-and-bound (`app.py:248`) is
   likewise over-engineered for n≤4. Simpler *and* optimal.
2. **Don't copy #1's infrastructure.** Redis, pub/sub, worker pools, Prisma,
   Docker — all correct for a production airport service, all pure liability
   in a 14-hour single-process demo. Take the *algorithm*, leave the plumbing.
