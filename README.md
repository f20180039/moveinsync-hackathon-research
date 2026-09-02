# hackathon-moveinsync — Hackathon Context

Isolated workspace for the MoveInSync / Bessemer Tech Catalyst mobility
hackathon (Bengaluru, ~2026-09-05). Nothing here touches other projects.

## Layout

```
hackathon-moveinsync/
├─ README.md            you are here
├─ specs/               ← START HERE
│  ├─ INDEX.md          router + the 5 things to actually do
│  ├─ 04-bengaluru-metro-dataset.md    🟢🟢 real metro data — do this first
│  ├─ 01-smart-airport-cabpooling.md   🟢  H3 corridor matching
│  ├─ 06-vroom.md                      🟢  best API/design template
│  ├─ 07-fleetpy.md                    🟢  feeder services + Alonso-Mora
│  ├─ 05-pyvrp.md                      🟢  constraint vocabulary
│  ├─ 08-timefold-quickstarts.md       🟡  the fairness policy
│  ├─ 02-rideshare-optimizer.md        🟡  pickup ordering
│  └─ 03-car-pooling-mern.md           🟡  context only
└─ reference/           8 repos — GIT-IGNORED, never committed (25 MB)
```

Sibling: **`../commute-os/`** — the build kit itself (design spec in
`docs/superpowers/specs/`). Separate repo on purpose: `commute-os` is code you
ship, this folder is research you read.

## How to use this on the day

1. Read `specs/INDEX.md` — 2 minutes. It ends with **"Answers to have ready"**
   for the questions judges actually ask.
2. Open only the 🟢 specs relevant to the statement.
3. Build in `../commute-os/`, guided by `../commute-os/PIVOT.md`.

## What happened here (2026-09-02)

Surveyed the five repos referenced in the PRD. **Three were mis-sold:**

| Repo | Outcome |
|---|---|
| `smart-aiport-cabpooling-backend` | ✅ Accurate. Real H3 + Redis matching. **Kept** |
| `RideShare-Optimizer` | ✅ Accurate. BFS/Prim's/TSP hand-written. **Kept** |
| `Car-Pooling-System` | ⚠️ Matching algorithm is commented out. **Kept for context** — it's a MoveInSync recruitment assignment, so it calibrates the baseline |
| `Carpool_Management_System` | ❌ Claimed "optimal allocation"; grep found none. **Removed, 53 MB** |
| `rideAndMove` | ❌ Claimed routing + admin + CDK; is 6 markdown files. **Removed** |

Then searched for the **actual problem class** — vehicle routing with time
windows, demand-responsive transport, semi-on-demand feeder services — rather
than the word "carpool", and added five better-aligned repos:

| Added | Why it aligns with MoveInSync |
|---|---|
| `bengaluru-metro-dataset` | 83 real stations, coords + graph + distances, CC0 |
| `pyvrp` | VRPTW/capacity/shift-duration/max-distance — enterprise commute, formally |
| `vroom` | Production API schema: skills, breaks, priority, shipments |
| `fleetpy` | TUM ride-pooling simulator: feeder services, EV charging, fleet sizing |
| `timefold-quickstarts` | Constraint patterns + employee rostering + fairness |

Eleven concrete design changes came out of it — see the tables in
`specs/INDEX.md`.

## Re-cloning

`reference/` is git-ignored, so a fresh checkout has none of it.

```sh
cd reference

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

git clone --depth 1 --filter=blob:none --sparse https://github.com/TimefoldAI/timefold-quickstarts.git timefold-quickstarts
git -C timefold-quickstarts sparse-checkout set use-cases/vehicle-routing use-cases/employee-scheduling
```

FleetPy is 662 MB upstream and 4.9 MB sparse; timefold 38.6 MB → 6.4 MB.

## Licences

MIT (`pyvrp`, `fleetpy`), BSD-2-Clause (`vroom`), Apache-2.0
(`timefold-quickstarts`), CC0 (`bengaluru-metro-dataset`, per its README —
GitHub detects no licence file, so attribute it explicitly). The three original
carpool repos carry no clear licence: **read them for ideas, don't copy their
code verbatim.**
