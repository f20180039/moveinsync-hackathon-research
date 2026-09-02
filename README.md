# MoveInSync Mobility Hackathon — Research & Design

Prep for the MoveInSync / Bessemer Tech Catalyst mobility hackathon
(Bengaluru, ~2026-09-05). The exact problem statement is **not known in
advance**, so this repo holds research and a design that stay useful whichever
theme lands.

**Nothing here is meant to be shipped as hackathon code.** It is reading
material: a deep analysis of eight open-source repos, plus a design spec.
Reference it, don't copy from it.

---

## Start here

| Read | What it gives you | Time |
|---|---|---|
| **[`specs/INDEX.md`](specs/INDEX.md)** | The router. Which repos matter, the 5 things worth doing, and **"Answers to have ready"** for the questions judges ask | 2 min |
| [`docs/superpowers/specs/2026-09-02-commute-os-design.md`](docs/superpowers/specs/2026-09-02-commute-os-design.md) | The design: problem-agnostic core + two solvers (Pool Merger, Metro Feeder Mesh) | 15 min |
| `specs/01…08-*.md` | Detailed per-repo technical specs — open only what you need | varies |

---

## Layout

```
.
├── README.md
├── specs/                    9 files, ~2,480 lines
│   ├── INDEX.md              ← router + spec-depth table + judge answers
│   ├── 01-smart-airport-cabpooling.md   🟢  H3 corridor matching       (342)
│   ├── 02-rideshare-optimizer.md        🟡  pickup ordering, ORS       (241)
│   ├── 03-car-pooling-mern.md           🟡  calibration only           (248)
│   ├── 04-bengaluru-metro-dataset.md    🟢🟢 real metro data — do first (273)
│   ├── 05-pyvrp.md                      🟢  constraint vocabulary      (329)
│   ├── 06-vroom.md                      🟢  best API/design template   (317)
│   ├── 07-fleetpy.md                    🟢  feeder svc + Alonso-Mora   (332)
│   └── 08-timefold-quickstarts.md       🟡  the fairness policy        (294)
├── docs/superpowers/specs/
│   └── 2026-09-02-commute-os-design.md  the design spec               (591)
└── reference/                LOCAL ONLY — git-ignored, never pushed (§Reference)
```

---

## What the research found

Five repos were supplied as "winning / production-grade" references. **Three
were mis-sold**, verified by grep and file listing rather than by reading
READMEs:

| Supplied repo | Outcome |
|---|---|
| `smart-aiport-cabpooling-backend` | ✅ Accurate. Real H3 + Redis corridor matching. **Kept** |
| `RideShare-Optimizer` | ✅ Accurate. BFS/Prim's/TSP hand-written. **Kept** |
| `Car-Pooling-System` | ⚠️ Matching algorithm is **commented out** (36% of the file). **Kept for calibration** — reportedly a MoveInSync recruitment assignment, so it shows where a competent candidate stalls |
| `Carpool_Management_System` | ❌ Claimed "real-time tracking + optimal allocation"; grep found **zero** distance/matching/allocation code. **Dropped** |
| `rideAndMove` | ❌ Claimed "Routing + Admin Panel + CDK"; is **6 markdown files, no code**, `datamodel.md` 0 bytes. **Dropped** |

Then searched for the **actual problem class** — vehicle routing with time
windows, demand-responsive transport, semi-on-demand feeder services — rather
than the word "carpool", and added five better-aligned repos:

| Added | Why it aligns |
|---|---|
| `bengaluru-metro-dataset` | 83 real Namma Metro stations: coords, graph edges, real inter-station distances (CC0) |
| `vroom` | Production VRP API schema — skills, breaks, priority, shipments, violations |
| `pyvrp` | State-of-the-art VRPTW solver; its constraint vocabulary maps 1:1 onto our policy engine |
| `fleetpy` | TUM ride-pooling simulator — semi-on-demand feeder, EV charging, Alonso-Mora |
| `timefold-quickstarts` | Constraint-based scoring patterns + employee rostering + fairness |

### Six findings that changed the design

1. **Real metro data retires a design assumption.** 83 stations with verified
   coordinates and real inter-station distances replace hand-typed guesses and a
   guessed "2.2 min/stop". The graph is **directed** — reverse edges must be
   synthesised, or feeder routing silently returns nothing outbound.
2. **The H3 corridor trick needs one non-obvious detail.** Every sorted-set
   member is stored with `score: 0`, because Redis only orders lexicographically
   when scores are equal. Miss it and a reimplementation silently returns
   garbage.
3. **A free third number for the dashboard.** PyVRP's bin-packing lower bound
   gives a theoretical cab floor, so you can show *baseline → achieved →
   theoretical floor* and state your own optimality gap.
4. **VROOM has a mode that does exactly what an admin console needs.** Plan mode
   evaluates a proposed route and reports structured violations instead of
   solving — so constraint evaluation belongs as a first-class entry point, not
   a filter inside the solver.
5. **Two independent systems agree on two rules.** Boarding cost splits into a
   per-stop and a per-passenger component (VROOM `setup`/`service`, FleetPy
   `std_bt`/`add_bt`); and serving everyone must outrank route efficiency
   (Timefold's medium score tier, FleetPy's `assignment_reward`).
6. **Fairness is the missing policy.** Optimise pure cost and the same employee
   in the far corner absorbs the detour every single day. That's how a corporate
   pooling programme actually dies — and it's invisible to every cost-only
   optimiser.

Eleven-plus concrete design changes and ~61 costed action items are tabulated in
[`specs/INDEX.md`](specs/INDEX.md) and each spec's final section.

---

## Reference clones (local only)

`reference/` is **git-ignored and never pushed** — three of the eight repos
carry no licence, so redistributing their source isn't ours to do. Clone them
yourself:

```sh
mkdir -p reference && cd reference

# small — clone whole
for u in maheshwarisharman/smart-aiport-cabpooling-backend \
         ashhwiithac22/RideShare-Optimizer \
         LohithMarneni/Car-Pooling-System \
         Vinayak-Chinchakhandi/Bengaluru-Metro-Network-Dataset \
         PyVRP/PyVRP \
         VROOM-Project/vroom ; do
  git clone --depth 1 "https://github.com/$u.git" "$(basename "$u")"
done

# large — sparse, or you will pull 700 MB
git clone --depth 1 --filter=blob:none --sparse https://github.com/TUM-VT/FleetPy.git fleetpy
git -C fleetpy sparse-checkout set src docs examples

git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/TimefoldAI/timefold-quickstarts.git timefold-quickstarts
git -C timefold-quickstarts sparse-checkout set use-cases/vehicle-routing use-cases/employee-scheduling
```

FleetPy is 662 MB upstream → 4.9 MB sparse; timefold 38.6 MB → 6.4 MB.
Every spec cites `file:line`, so the clones are only needed to follow a citation.

---

## Licence & attribution

The **specs and design in this repo are our own analysis and writing**, and
quote only short excerpts of the repos they discuss, with attribution, for
technical commentary.

Upstream licences, for anything you lift:

| Repo | Licence |
|---|---|
| `pyvrp`, `fleetpy` | MIT |
| `vroom` | BSD-2-Clause |
| `timefold-quickstarts` | Apache-2.0 |
| `bengaluru-metro-dataset` | CC0 asserted in its README (no `LICENSE` file — attribute explicitly) |
| `smart-aiport-cabpooling-backend`, `RideShare-Optimizer`, `Car-Pooling-System` | **none declared — read for ideas, do not copy code** |

Papers worth citing: PyVRP arXiv:2403.13795 · FleetPy arXiv:2207.14246 ·
Alonso-Mora et al., *PNAS* 2017.
