# Reference Repo Index — MoveInSync Hackathon

Repos cloned to `../reference/` (shallow/sparse, git-ignored).
Surveyed 2026-09-02, revised after pruning.

This file is the **router**: read it, open the one or two specs you need, ignore
everything else.

## Verdict table

| # | Repo | What it is | Reuse | Spec |
|---|---|---|---|---|
| **04** | `bengaluru-metro-dataset` | 83 real Namma Metro stations: coords, graph edges, real inter-station distances. CC0 | 🟢🟢 **HIGHEST** | [04](04-bengaluru-metro-dataset.md) |
| **01** | `smart-aiport-cabpooling-backend` | Working H3 + Redis corridor matching. TS | 🟢 **HIGH** | [01](01-smart-airport-cabpooling.md) |
| **06** | `vroom` | Production VRP solver; **its API schema is the best design template here** | 🟢 **HIGH** | [06](06-vroom.md) |
| **07** | `fleetpy` | TUM ride-pooling fleet simulator. Semi-on-demand feeder + Alonso-Mora | 🟢 **HIGH** | [07](07-fleetpy.md) |
| **05** | `pyvrp` | State-of-the-art VRP solver. Its constraint vocabulary validates our policy list | 🟢 **HIGH** | [05](05-pyvrp.md) |
| **08** | `timefold-quickstarts` | Constraint-based solver patterns + employee rostering | 🟡 **MED-HIGH** | [08](08-timefold-quickstarts.md) |
| **02** | `RideShare-Optimizer` | BFS/Prim's/TSP hand-implemented. Python/Streamlit | 🟡 **MED** | [02](02-rideshare-optimizer.md) |
| **03** | `Car-Pooling-System` | MERN CRUD; matching commented out. Kept for **context** — it's a MoveInSync recruitment assignment | 🟡 **LOW** | [03](03-car-pooling-mern.md) |

Disk: 25 MB total (662 MB of FleetPy reduced to 4.9 MB by sparse clone).

### Removed 2026-09-02

- ❌ `Carpool_Management_System` — PRD claimed "real-time tracking + optimal
  allocation". Grep found **zero** distance/matching/allocation code. Leaflet +
  Firebase + a 45 MB vendored chat UI kit. **53 MB deleted.**
- ❌ `rideAndMove` — PRD claimed "Routing + Admin Panel + CDK". Actually **6
  markdown files, no code**; `doc/datamodel.md` was 0 bytes. **Deleted.**

Lesson worth carrying: three of the five PRD-supplied repos were mis-sold. The
replacements were found by searching for the *actual problem class* — vehicle
routing with time windows, demand-responsive transport, semi-on-demand feeder
services — rather than for the word "carpool".

## Do these five things

Ordered by value per minute. Total ≈ 3 hours, and it upgrades the design
materially.

1. **Copy the metro CSVs into `commute-os/data/`** ([04](04-bengaluru-metro-dataset.md))
   — retires design assumption §17 #1, and replaces guessed per-stop timing with
   real inter-station distances. *Zero algorithm work.* Do this first.
2. **Read `vroom/docs/API.md` end to end** ([06](06-vroom.md)) — highest
   value-per-minute document in the set. Adopt `skills`, an array of time
   windows per trip, and `priority`.
3. **Add the `detour-fairness` policy** ([08](08-timefold-quickstarts.md)) — the
   best idea recovered that wasn't already in the design. Stops the same
   employee absorbing the detour every day.
4. **Port the insertion heuristic** ([07](07-fleetpy.md) §5) — the right
   primitive for Approve and Revert, instead of re-running the whole solver.
5. **Implement the reversed-suffix H3 prefix scan** ([01](01-smart-airport-cabpooling.md) §4)
   — O(log n) corridor candidates, ~40 lines, no Redis.

## Findings that change the commute-os design

| Change | Source | Why |
|---|---|---|
| Real metro coords + distances | 04 | Retires §17 assumption #1 outright |
| Reversed H3 suffix key for convergent trips | 01 §4 | Airport is divergent; commute is convergent |
| Suitability checks as `skills` matching | 06 §2 | One mechanism instead of N special cases |
| Array of time windows per trip | 06 §5 | Employees have two windows, not one |
| `priority` for over-subscription | 06 §4 | Peak demand exceeds supply; handle it openly |
| Driver `breaks`, not just a 12 h cap | 06 §3 | Real labour compliance |
| **`detour-fairness` as policy #10** | 08 §3 | Pooling dies on employee trust, not arithmetic |
| `vehiclesUsed` as the headline metric | 05 §3 | "138 cabs instead of 174" > "saved 8.2 km" |
| Vector capacity `[seats, luggage, wheelchair]` | 05 §4 | Accessibility, ~free to add |
| Insertion heuristic for Approve/Revert | 07 §5 | Don't re-solve to approve one merge |
| Never reward dropping trips | 08 §4 | `MAXIMIZE_VISITS_ASSIGNED` outranks travel time |
| Brute-force pickup order at n≤4 | 02 §3 | 24 permutations — exact beats heuristic |

## Answers to have ready

Judges ask these. The specs give real answers rather than bluffs.

- *"How do you find candidates at scale?"* → H3 corridor keys in a sorted
  index, O(log n) prefix scan, not an O(n²) distance matrix. ([01](01-smart-airport-cabpooling.md) §7)
- *"Is your merge optimal?"* → No. Clarke-Wright savings, the standard VRP
  construction heuristic since 1964, typically 5–10% off optimal, solved in 2 ms
  so it re-plans on every cancellation. ([02](02-rideshare-optimizer.md) §3)
- *"Why not a real solver?"* → For a live dispatch board, responsiveness beats
  optimality; the constraint model is identical either way. ([05](05-pyvrp.md) §5)
- *"How does this scale to a real fleet?"* → Alonso-Mora RTV formulation, which
  FleetPy implements. The policy engine transfers unchanged because it's
  independent of the assignment algorithm. ([07](07-fleetpy.md) §4)
- *"What is this called in the literature?"* → A semi-on-demand feeder service.
  ([07](07-fleetpy.md) §3)
