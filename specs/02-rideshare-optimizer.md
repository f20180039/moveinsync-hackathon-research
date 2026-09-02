# 02 — RideShare-Optimizer · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/ashhwiithac22/RideShare-Optimizer` |
| **Reuse** | 🟡 **MEDIUM** — for the maths and one API, not the code |
| **Stack** | Python · Streamlit · networkx · folium · geopy · polyline · OpenRouteService |
| **Size** | 192 KB · **one 1186-line `app.py`** · last commit 2025-10-25 |
| **Licence** | none declared |
| **Local** | `reference/RideShare-Optimizer/` |

A single-file Streamlit app: enter rider origins and destinations, it builds a
`networkx` graph, fetches real routes from OpenRouteService, computes a shared
route, and renders it on a folium map.

The PRD's claim ("BFS, Prim's, TSP") is **accurate** — all three are
hand-implemented rather than pulled from a library, which makes them unusually
easy to read and port. No tests, no module structure.

---

## 1. Function inventory

| Line | Function | Verdict |
|---|---|---|
| `:27` | `geocode_location()` | Nominatim/geocoder. Skip — you use fixtures |
| `:80` | `get_ors_route()` | **OpenRouteService** — genuinely useful (§4) |
| `:163` | `calculate_route()` | thin wrapper over `get_ors_route` |
| `:177` | `bfs_shortest_path()` | **misnamed — it's Dijkstra** (§2) |
| `:209` | `prims_minimum_spanning_tree()` | correct Prim's. **A trap** (§5) |
| `:248` | `class TSPSolver` | branch-and-bound TSP (§3) |
| `:341` | `find_path_cost()` | sums edge weights along a path |
| `:352` | `find_optimal_pickup_order()` | **the relevant one** (§3) |
| `:394` | `find_shared_route()` | pickup order + drop order end to end |

Roughly half the file is Streamlit UI and folium rendering.

---

## 2. `bfs_shortest_path` is Dijkstra

```python
queue = []
heapq.heappush(queue, (0, [source]))
while queue:
    current_weight, path = heapq.heappop(queue)
    ...
    for neighbor in graph.neighbors(current_node):
        edge_weight = graph[current_node][neighbor].get(weight_attr, 1)
        heapq.heappush(queue, (current_weight + edge_weight, path + [neighbor]))
```

A **priority queue keyed on cumulative weight** is Dijkstra. BFS uses a FIFO
queue and only finds shortest paths on unweighted graphs. The `from collections
import deque` at `:9` is imported and never used for this — a leftover from an
actual BFS that was replaced.

Two notes if you port it:

- It pushes **whole paths** onto the heap rather than a predecessor map. Simple
  to read, O(V) memory per queue entry. Fine at this scale, wasteful in general.
- Don't repeat the naming error in your own code or your pitch. Calling Dijkstra
  "BFS" to a judge who knows the difference is a needless own goal — and the
  PRD's reference list propagated exactly that claim.

**You don't need it.** commute-os has a precomputed distance/route cache
(`routes.cache.json`), so shortest-path search never happens at runtime. Graph
search is only relevant if you build a road network, which the design
deliberately avoids.

---

## 3. Pickup ordering — and why to simplify it

### 3.1 What they do (`:352`)

```python
def find_optimal_pickup_order(graph, rider_origins, destination, weight_attr='distance'):
    if len(rider_origins) == 1:
        return rider_origins
    best_order, best_distance = [], float('inf')
    for start_rider in rider_origins:            # multi-start
        current_order, remaining = [start_rider], [r for r in rider_origins if r != start_rider]
        current_location, total_distance = start_rider, 0
        while remaining:                         # greedy nearest-neighbour
            next_rider, next_distance = None, float('inf')
            for rider in remaining:
                path, dist = bfs_shortest_path(graph, current_location, rider, weight_attr)
                if path and dist < next_distance:
                    next_distance, next_rider = dist, rider
            ...
        final_path, final_dist = bfs_shortest_path(graph, current_location, destination, weight_attr)
        if total_distance + final_dist < best_distance:
            best_distance, best_order = total_distance + final_dist, current_order
    return best_order
```

**Multi-start nearest-neighbour.** Try each rider as the first pickup, greedily
hop to the nearest remaining rider, add the run to the destination, keep the best
start. Cost: O(n²) hops × O(n) starts × Dijkstra per hop.

Reasonable for large n. But **a cab seats 4.**

### 3.2 What to do instead — brute force, exact

With n ≤ 4 pickups there are at most 4! = **24** orderings. Enumerate them all
and the answer is optimal, in microseconds:

```ts
// solvers/pickup-order.ts
// PURPOSE: optimal pickup sequence for a pooled cab.
// PIVOT: exact while seats <= 6 (720 perms). Above that, switch to nearest-neighbour.
// SAFE-TO-DELETE: no
export function bestPickupOrder(pickups: LatLng[], office: LatLng, d: Dist): LatLng[] {
  let best = pickups, bestKm = Infinity
  for (const perm of permutations(pickups)) {          // <= 24 for a 4-seater
    let km = 0
    for (let i = 1; i < perm.length; i++) km += d(perm[i - 1], perm[i])
    km += d(perm[perm.length - 1], office)
    if (km < bestKm) { bestKm = km; best = perm }
  }
  return best
}
```

Note the boundary: 5 seats → 120 permutations, 6 → 720, still trivial. A
12-seat shuttle → 479 million, so **Metro Feeder Mesh's shuttle legs must not
use this** — that's where nearest-neighbour or insertion (spec 07 §3) belongs.
Put that threshold in the PIVOT comment so it isn't rediscovered painfully.

### 3.3 `TSPSolver` (`:248`) — over-engineered here, worth understanding

A textbook branch-and-bound TSP:

- `first_min(i)` / `second_min(i)` — the two cheapest edges at node `i`
- `tsp_rec(adj, curr_bound, curr_weight, level, curr_path, visited)` — DFS with
  pruning: `if new_bound + curr_weight < self.final_res` else prune
- lower bound = sum of the two minimum edges per node (halved), the classic
  relaxation

Correct, and completely unnecessary at n ≤ 4 where brute force is exact. Read it
to understand *why* bounding exists, then don't port it.

### 3.4 `find_shared_route` (`:394`) — read for structure

Handles the general many-origins-to-many-destinations case: if all origins
coincide, one pickup; otherwise find the furthest-apart destination pair, order
pickups toward it, then greedily order drop-offs from the last pickup.

**Your problem is simpler and you should keep it that way.** Login trips are
many-origins → *one* destination, so drop ordering doesn't exist. The design's
`gate-spread` policy (max 2 gates) is what keeps it that way deliberately. Don't
import this generality.

---

## 4. OpenRouteService — the genuinely useful find

`:80`:

```python
headers = {'Authorization': ORS_API_KEY, 'Content-Type': 'application/json; charset=utf-8'}
body = {"coordinates": [[start[1], start[0]], [end[1], end[0]]],   # ORS wants [lng, lat]
        "instructions": "false", "preference": "fastest"}
requests.post(f'https://api.openrouteservice.org/v2/directions/{profile}/geojson', ...)
# then:
distance = feature['properties']['segments'][0]['distance'] / 1000   # km
duration = feature['properties']['segments'][0]['duration'] / 60     # minutes
```

Why this matters: **ORS has a free API tier and no billing-card requirement**,
unlike Google Directions. That makes it a materially lower-risk live fallback
for a hackathon. It fits `core/routing.ts` as a middle tier:

```
routes.cache.json  →  OpenRouteService (free tier)  →  haversine × 1.3
```

The cache stays first — design goal G5 is unchanged — but if you *do* need a
live call for an off-fixture location, ORS won't fail on a billing problem at
09:00 on demo day. Note the `[lng, lat]` ordering (same as VROOM, opposite of
Google) and that `profile` supports `driving-car` and `driving-bike`, so a
two-wheeler feeder mode is one string away.

**Their cost model, worth comparing to yours:**

| | base | per km |
|---|---|---|
| `driving-car` | ₹50 | ₹15 |
| `driving-bike` | ₹20 | ₹8 |
| **commute-os `ledger.MODEL`** | **₹60** | **₹18** |

Independent numbers within ~15% of the design's assumptions. Weak evidence, but
it's the only external sanity check available on those constants, and it points
the same way.

---

## 5. Prim's MST — a trap worth understanding

`:209` is a correct Prim's implementation (heap of frontier edges, expand while
`(u in mst) != (v in mst)` to avoid cycles).

**But an MST is the wrong structure for a route.** A spanning tree is the
cheapest way to *connect* a set of points; a cab route is the cheapest way to
*visit* them in sequence. A tree may branch — a vehicle cannot. So MST cost
systematically **under-estimates** true route distance, and using it as a route
cost will overstate your savings.

Don't port it. If asked why not, one sentence: *"a spanning tree can branch; a
vehicle can't."*

MST cost *is* a legitimate lower bound for TSP, which is how `TSPSolver`'s
`first_min`/`second_min` bounding uses the same idea correctly. Legitimate there;
irrelevant at n ≤ 4.

This matters beyond this repo: "we used Prim's algorithm" sounds impressive, and
the PRD lists it as a selling point of this reference. Recognising that it's the
wrong tool is the more valuable takeaway than the implementation.

---

## 6. What to ignore

Streamlit UI (roughly half the file), folium/`DivIcon` rendering,
`geocode_location`, `random`-seeded demo data, `find_path_cost`. The file has no
tests and no module boundaries — read it in a viewer, port two things, close it.

---

## 7. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | Brute-force pickup ordering, exact at n≤4 | `solvers/pickup-order.ts` | 30 min |
| 2 | Document the seat threshold where brute force stops | same, header comment | 5 min |
| 3 | ORS as middle tier in the routing chain | `core/routing.ts` | 45 min |
| 4 | Sanity-check `ledger.MODEL` against their ₹50/₹15 | `core/ledger.ts` | 10 min |
| 5 | Do **not** port Prim's; note why in the design | — | 0 |

Small repo, three real takeaways, and one useful anti-lesson.
