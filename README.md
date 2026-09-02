# hackathon-moveinsync — Hackathon Context

Isolated workspace for the MoveInSync / Bessemer Tech Catalyst mobility
hackathon (Bengaluru, ~2026-09-05). Nothing here touches other projects.

## Layout

```
hackathon-moveinsync/
├─ README.md            you are here
├─ specs/               ← START HERE
│  ├─ INDEX.md          router: which reference repo is worth reading, and why
│  ├─ 01-smart-airport-cabpooling.md   🟢 HIGH  — the best algorithm
│  ├─ 02-rideshare-optimizer.md        🟢 HIGH  — the maths, not the code
│  ├─ 03-car-pooling-mern.md           🟡 LOW-MED
│  ├─ 04-carpool-management.md         🔴 LOW
│  └─ 05-rideandmove.md                🔴 NONE  — empty repo
└─ reference/           5 shallow clones — GIT-IGNORED, never committed
```

Sibling: **`../commute-os/`** — the build kit itself (design spec in
`docs/superpowers/specs/`). Kept as a separate repo on purpose: `commute-os` is
code you ship, this folder is research you read.

## How to use this on the day

1. Read `specs/INDEX.md` — 2 minutes, tells you what to ignore.
2. Read only the specs marked 🟢. Repos 4 and 5 were mis-sold in the PRD.
3. Lift from `../commute-os/`, guided by `../commute-os/PIVOT.md`.

## Survey findings (2026-09-02)

Of the five "winning / production-grade" reference repos in the PRD, **two
deliver what was claimed**:

- ✅ `smart-aiport-cabpooling-backend` — real H3 + Redis matching algorithm
- ✅ `RideShare-Optimizer` — real BFS/Prim's/TSP implementations
- ⚠️ `Car-Pooling-System` — matching algorithm is **commented out**, never shipped
- ❌ `Carpool_Management_System` — **zero** distance or allocation code (claimed both)
- ❌ `rideAndMove` — **6 markdown files, no code**; `datamodel.md` is 0 bytes

Verified by grep and file listing, not by reading READMEs. Details in each spec.

## Re-cloning

`reference/` is git-ignored, so a fresh checkout has none of it:

```sh
cd reference
for u in parthkvv/Carpool_Management_System \
         maheshwarisharman/smart-aiport-cabpooling-backend \
         ashhwiithac22/RideShare-Optimizer \
         LohithMarneni/Car-Pooling-System \
         iavofficial/rideAndMove ; do
  git clone --depth 1 "https://github.com/$u.git" "$(basename "$u")"
done
```

Disk note: `Carpool_Management_System` is 53 MB, ~45 MB of which is a vendored
CometChat UI kit. Safe to delete — see spec 04.
