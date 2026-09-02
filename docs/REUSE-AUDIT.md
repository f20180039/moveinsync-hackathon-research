# Reuse Audit — what to extract, what to depend on, what to write

**Date:** 2026-09-02 · companion to `superpowers/plans/2026-09-02-commute-os-core-engine.md`

Question: *can anything I want to build be extracted as-is from the reference
repos?* Answer: **almost nothing — but that is the wrong place to look.** The
real wheel-reinvention risk is hand-rolling what npm already provides.

---

## 1. The reference repos: one extractable artifact

Two constraints compound, and they compound badly.

| Repo | Licence | Language | Copy code? |
|---|---|---|---|
| `bengaluru-metro-dataset` | **CC0** | **CSV data** | ✅ **YES — extract as-is** |
| `pyvrp` | MIT | Python + C++ | ⚠️ legal, wrong language |
| `fleetpy` | MIT | Python | ⚠️ legal, wrong language |
| `vroom` | BSD-2-Clause | C++ | ⚠️ legal, wrong language |
| `timefold-quickstarts` | Apache-2.0 | Java | ⚠️ legal, wrong language |
| `smart-aiport-cabpooling-backend` | **none** | **TypeScript** | ❌ no licence |
| `RideShare-Optimizer` | **none** | Python | ❌ no licence |
| `Car-Pooling-System` | **none** | JavaScript | ❌ no licence |

**The cruel symmetry: the one repo whose code would drop straight into a
TypeScript app has no licence, and every repo we may legally copy is in a
language we cannot use.**

So exactly one thing is extractable verbatim — **the metro CSVs** — and Plan 1
Task 4 already does that, with CC0 attribution in `data/README.md`.

**What is still legitimately reusable: the ideas.** Algorithms and techniques
are not copyrightable. The H3-corridor-as-lexicographic-prefix technique, the
Clarke-Wright savings adaptation, the four-tier score, the insertion heuristic,
the fairness constraint — all free to reimplement, and that is exactly what
`specs/01`–`08` captured. The specs *are* the extraction; the code was never
the deliverable.

**Do not** copy from the three unlicensed repos even though `smart-airport` is
TypeScript and would be the easiest lift in the set. No licence means no grant.

---

## 2. Where we ARE reinventing the wheel: Plan 1

Plan 1 hand-writes several things that mature, permissive npm packages do
better. All versions and licences below verified against the npm registry on
2026-09-02.

| Plan 1 code | Replace with | Version | Licence | Why |
|---|---|---|---|---|
| `geo.ts` haversine + ray-casting point-in-polygon | `@turf/distance`, `@turf/boolean-point-in-polygon`, `@turf/helpers` | 7.4.0 | MIT | Battle-tested geodesy and polygon edge cases (vertex hits, antimeridian) we would otherwise get subtly wrong |
| `metro.ts` hand CSV parser | `papaparse` | 5.7.0 | MIT | **0 runtime deps.** Our CSV is unquoted today; a hand parser breaks the day the data changes |
| `metro.ts` hand Dijkstra | `graphology` + `graphology-shortest-path` | 0.26.0 / 2.1.0 | MIT | Mine re-sorts the whole queue every iteration — O(n² log n). Genuinely sloppy, and a real heap is free |
| `mulberry32` in `generate-fixtures.ts` | `seedrandom` | 3.0.5 | MIT | 0 deps, well-tested, same determinism guarantee |
| `FIRST[]` name array | `@faker-js/faker` (seeded) | 10.6.0 | MIT | 0 deps, and realistic Indian-locale names beat 22 hand-typed ones |
| **Plan 2** H3 corridor keys | `h3-js` | 4.5.0 | Apache-2.0 | 0 deps. **The same library the reference repo used.** Never hand-write H3 |
| **Plan 3** map | `maplibre-gl` | 6.6.0 | BSD-3-Clause | Already the design's choice |

⚠️ **Install `@turf/*` sub-packages, not `@turf/turf`** — the meta-package pulls
**117 runtime dependencies**. Three sub-packages pull a handful.

**Net effect: roughly 40% of Plan 1's hand-written code becomes a dependency**,
and the parts that remain are the parts worth owning.

---

## 3. What must stay hand-written — and should

Not reinvention. There is no wheel to reuse.

| Module | Why no library exists |
|---|---|
| `core/policies/*` (all ten) | **This is the moat.** No package encodes "do not pool a lone female employee on a night shift" or "this employee has absorbed the detour four days running" |
| `core/ledger.ts` | The cost and carbon model *is* the pitch. A library would hide the assumptions judges ask about |
| `core/scenario.ts` | Domain metrics. `theoreticalFloor` is three lines |
| `core/policy.ts` | The four-tier engine is ~60 lines of domain logic |
| `core/clock.ts` | ~40 lines. A dependency costs more than it saves |
| `core/routing.ts` | Cache-then-estimate resolution; trivial and demo-critical |
| **Plan 2** Clarke-Wright savings | **No maintained JS/TS VRP solver exists.** PyVRP is Python+C++, VROOM is C++, jsprit and Timefold are Java. ~50 lines, and it is the differentiator |

That last row is worth saying on stage if asked why we did not use an
off-the-shelf solver: *there isn't one in this language, and at 200 trips a
construction heuristic that returns in 2 ms is the right tool anyway.*

---

## 4. Action

Plan 1 needs revising in five tasks — 2 (`geo`), 4 (`metro`), 11 (`fixtures`),
plus the dependency list in Task 1 and the boundary test's allowance for the new
imports. Tasks 3, 5, 6, 7, 8, 9 and 10 are unaffected: they are all domain logic.

Expected `package.json` after revision:

```json
"dependencies": {
  "@turf/boolean-point-in-polygon": "^7.4.0",
  "@turf/distance": "^7.4.0",
  "@turf/helpers": "^7.4.0",
  "graphology": "^0.26.0",
  "graphology-shortest-path": "^2.1.0",
  "papaparse": "^5.7.0",
  "seedrandom": "^3.0.5"
},
"devDependencies": {
  "@faker-js/faker": "^10.6.0",
  "@types/node": "20.11.30",
  "@types/papaparse": "^5.5.2",
  "@types/seedrandom": "^3.0.8",
  "tsx": "4.7.1",
  "typescript": "5.4.3",
  "vitest": "1.6.0"
}
```

`h3-js` is added in Plan 2, `maplibre-gl` in Plan 3.
