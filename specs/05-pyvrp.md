# 05 — PyVRP

**Reuse: 🟢 HIGH — for its constraint vocabulary, which validates the design.**
`github.com/PyVRP/PyVRP` · Python + C++ · 3.6 MB · ⭐685 · MIT ·
updated 2026-08-31 · has a published paper (arXiv 2403.13795)

## 1. What it is

A state-of-the-art open-source VRP solver: Hybrid Genetic Search over a C++ core
with a Python API. Handles CVRP, VRPTW, prize-collecting, multi-depot,
multi-profile. Actively maintained, MIT-licensed, academically credible.

**You will not run this in a Next.js app.** Its value is different and larger:
it tells you the *correct vocabulary* for the problem you're modelling.

## 2. The finding that matters

`pyvrp/Model.py:428` — `add_vehicle_type()` parameters map almost **one-to-one**
onto the nine policies in the commute-os design (§7), which were derived
independently from the PRD's edge cases:

| commute-os policy | PyVRP native parameter |
|---|---|
| `driver-hours` (12 h cap) | `shift_duration` |
| `ev-range` (80% of range) | `max_distance` |
| `seat-capacity` | `capacity` (multi-dimensional!) |
| `time-window` | `tw_early` / `tw_late` |
| `gender-safety` | `add_client_group(required=False)` — mutually exclusive groups |
| `zone-confidence` | `prize` + `required=False` — optional clients |
| ledger `cabRatePerKm` | `unit_distance_cost` |
| ledger `driverCostPerHour` | `unit_duration_cost` |
| ledger `cabBaseFarePerTrip` | `fixed_cost` |
| EV vs ICE road behaviour | `profile` — per-vehicle-type routing profiles |

`Model.py:237` — `add_client()` adds `service_duration`, `release_time`,
`prize`, `required`, `group`.

**Why this is worth knowing:** the design's policy list wasn't guesswork. A
mature solver, built by operations-research people, exposes the same
constraints under established names. That's independent confirmation the model
is right — and it gives you the vocabulary to *say so*. "Our policy engine
covers capacity, time windows, shift duration, max distance and mutually
exclusive client groups" lands very differently from "we wrote nine if-checks."

## 3. `minimise_fleet` — steal this objective

`pyvrp/minimise_fleet.py` solves a different question than "shortest routes":
**what is the fewest vehicles that can serve this demand feasibly?**

For an enterprise commute buyer that *is* the question. Not "we saved 8.2 km"
but "the same 200 employees move with 138 cabs instead of 174." Cabs are the
cost line; kilometres are a proxy for it.

Add `vehiclesUsed` to `core/scenario.ts::Metrics` (already in the design) and
lead the KPI strip with it.

## 4. Multi-dimensional capacity — a subtle upgrade

`capacity: int | list[int]` — capacity is a **vector**, not a scalar. For
employee transport that's immediately useful:

```
capacity = [seats, luggage, wheelchair_slots]
```

Your `seat-capacity` policy currently checks one scalar. Making it a vector
costs nothing now and handles accessibility requirements — an angle almost
nobody at a mobility hackathon will have considered, and one an enterprise
buyer with accessibility obligations will care about.

## 5. What NOT to do

**Do not try to run PyVRP in the demo.** It needs Python + a compiled C++
extension; your app is Next.js/TypeScript. Bridging them costs hours and adds a
process boundary that can die on stage — precisely the risk the design's G5
("zero demo-time external dependencies") exists to prevent.

Clarke-Wright in TypeScript stays the right call: milliseconds, no dependency,
re-plans live. PyVRP is the reference you cite, not the code you ship.

If asked *"why not a real solver?"*: **"Clarke-Wright gives us a solution in
2 ms so we can re-plan every time a trip cancels. PyVRP's HGS would give us
maybe 8% better routes in 30 seconds. For a live dispatch board, responsiveness
beats optimality — and the constraint model is the same either way."**

## 6. Worth reading

- `pyvrp/Model.py` — the whole modelling API, ~600 readable lines
- `pyvrp/minimise_fleet.py` — fleet minimisation objective
- `pyvrp/plotting/` — route-plot conventions worth borrowing for `MapCanvas`
- The paper (arXiv 2403.13795) — one citation makes your algorithm section credible

## 7. Verdict

Read `Model.py` once. Rename your policies to match its vocabulary, add
`vehiclesUsed` as the headline metric, and make `seat-capacity` a vector. Ship
nothing from it. ~30 minutes for a meaningful credibility upgrade.
