# 02 — RideShare-Optimizer

**Reuse: 🟢 HIGH — for the maths, not the code.**
`github.com/ashhwiithac22/RideShare-Optimizer` · Python/Streamlit ·
**one 1186-line `app.py`** · last commit 2025-10-25

## 1. What it actually is

A single-file Streamlit app: enter rider origins/destinations, it builds a
`networkx` graph, geocodes via OpenRouteService, and renders shared routes on a
`folium` map. The PRD's claim ("BFS, Prim's, TSP") is **accurate** — all three
are hand-implemented rather than called from a library, which makes them easy to
read and port.

Stack: `streamlit`, `networkx`, `folium`, `geopy`, `polyline`, `requests`.
Nothing here is directly usable in a Next.js app — **port the algorithms, don't
copy the file.**

## 2. The functions that matter

| Line | Function | Verdict |
|---|---|---|
| `app.py:27` | `geocode_location()` | Nominatim/geocoder. Skip — you use fixtures. |
| `app.py:80` | `get_ors_route()` | **OpenRouteService** call. Worth noting — see §4. |
| `app.py:177` | `bfs_shortest_path()` | Misnamed: it's Dijkstra (uses `heapq` + weights). Skip — you have cached routes. |
| `app.py:209` | `prims_minimum_spanning_tree()` | Correct Prim's. **Not useful** — see §5. |
| `app.py:248` | `class TSPSolver` | Branch-and-bound TSP with `first_min`/`second_min` bounding. Over-engineered — see §3. |
| `app.py:352` | `find_optimal_pickup_order()` | **The relevant one.** Multi-start nearest-neighbour. |
| `app.py:394` | `find_shared_route()` | Pickup order + drop order end-to-end. Read for structure. |

## 3. `find_optimal_pickup_order` — and why to simplify it

Their approach: for **each** rider as a candidate first pickup, greedily hop to
the nearest remaining rider, then to the destination; keep whichever start gave
the lowest total. Multi-start nearest-neighbour, O(n³) with the inner Dijkstra.

It's a reasonable heuristic for large n. **But a cab seats 4.**

With n ≤ 4 pickups there are at most 4! = **24 orderings**. Enumerate all of
them and you get the *exact* optimum in microseconds:

```ts
// solvers/pool-merger.ts — exact for n<=4, no heuristic needed
function bestPickupOrder(pickups: LatLng[], office: LatLng): LatLng[] {
  let best = pickups, bestKm = Infinity
  for (const perm of permutations(pickups)) {         // <= 24
    let km = 0
    for (let i = 1; i < perm.length; i++) km += dist(perm[i-1], perm[i])
    km += dist(perm[perm.length-1], office)
    if (km < bestKm) { bestKm = km; best = perm }
  }
  return best
}
```

**This is both simpler and strictly better than the reference.** Their
nearest-neighbour can be 25% off optimal; brute force cannot be wrong. Their
`TSPSolver` branch-and-bound solves the same problem with vastly more machinery
and no benefit at this size.

Worth saying on stage if asked: *"pickup ordering is a TSP, but bounded at four
seats it's 24 permutations — so we solve it exactly rather than approximating."*
Knowing **when not to** reach for the clever algorithm reads as competence.

## 4. OpenRouteService — a genuinely useful find

`app.py:80` uses ORS instead of Google Directions. ORS has a free API tier and
no billing card requirement, which makes it a better *live* fallback than Google
for a hackathon. Fits `core/routing.ts` as a middle tier:

```
cache → ORS (free tier) → haversine × 1.3
```

Still not on the demo critical path — the cache stays first. But it's a
lower-risk enhancement than Google.

## 5. Prim's MST — a trap, and a useful trap to understand

Prim's builds a minimum spanning **tree**. A cab route is a **path**. An MST
over pickups tells you the cheapest way to *connect* them all, not the cheapest
way to *visit* them in sequence — a tree can branch, a cab cannot. Using MST
cost as a route cost systematically **under-estimates** the real distance.

Don't port it. If a judge asks why not, the answer is one sentence: *"a spanning
tree can branch; a vehicle can't."*

(MST cost *is* a valid lower bound for TSP, which is how their `TSPSolver` uses
`first_min`/`second_min` for bounding. Legitimate there, irrelevant at n≤4.)

## 6. What to ignore

Streamlit UI (~half the file), folium rendering, geocoding, `DivIcon` markers,
`random`-based demo data. Note the file has **no tests and no module structure**
— it is a 1186-line script. Read it in a viewer, port the two ideas, close it.

## 7. Verdict

Two takeaways, both small:
1. **Brute-force pickup ordering** at n≤4 — exact, ~15 lines, replaces their
   heuristic outright.
2. **OpenRouteService** as a keyless-ish middle tier in `core/routing.ts`.

And one anti-lesson: their MST detour is a wrong turn worth recognising, since
"we used Prim's algorithm" sounds impressive and is, here, incorrect.
