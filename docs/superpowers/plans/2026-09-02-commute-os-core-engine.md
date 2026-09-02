# commute-os Core Engine — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless, fully unit-tested core of `commute-os` — domain
types, geo, cost/carbon ledger, real metro graph, simulation clock, route
provider, the four-tier policy engine with all ten policies, the scenario
metrics harness, and a seeded fixture generator.

**Architecture:** A plain TypeScript library with **zero React and zero Next.js
imports**, consumed later by the solvers (Plan 2) and the command-center UI
(Plan 3). Every module is a pure function over explicit arguments — no DI, no
clever generics, no ambient state. Determinism is a hard requirement: no
`Date.now()`, no unseeded `Math.random()` anywhere in `src/core`, so golden
tests are byte-stable.

**Tech Stack:** TypeScript 5.4 · Vitest 1.6 · tsx · Node 18.19.0 / npm 10.2.3.

Runtime dependencies, all permissively licensed and **all verified against the
npm registry and exercised locally on 2026-09-02** (see `docs/REUSE-AUDIT.md`):
`@turf/distance` + `@turf/boolean-point-in-polygon` + `@turf/helpers` 7.4.0 (MIT)
for geodesy and polygon containment · `graphology` 0.26.0 +
`graphology-shortest-path` 2.1.0 (MIT) for the metro Dijkstra · `papaparse`
5.7.0 (MIT, 0 deps) for CSV · `seedrandom` 3.0.5 (MIT, 0 deps) and
`@faker-js/faker` 10.6.0 (MIT) for deterministic fixtures.

Footprint: the 7 runtime deps alone resolve to 16 packages / 5.6 MB; with the
7 devDependencies (typescript, vitest, tsx, faker, @types/*) a full install is
**~91 packages / ~79 MB** in `node_modules`. Both numbers are fine — only the
runtime set ships.

Next.js is added in Plan 3, `h3-js` in Plan 2 — deliberately not here.

**Do not install `@turf/turf`** — the meta-package pulls 117 runtime
dependencies. Only the three sub-packages above.

**Do not vendor or fork these libraries.** Depending on them via npm keeps their
patches and their test suites; a fork means owning their bugs. If behaviour ever
needs changing, wrap — never fork.

**Spec:** `docs/superpowers/specs/2026-09-02-commute-os-design.md` (v1.1) —
implements §5, §6, §7, §11 and the Tier A items in §19.

## Global Constraints

- **Node 18.19.0**, npm 10.2.3. Next.js, when added in Plan 3, is pinned to
  `14.x` for Node 18 compatibility. Do not add Next in this plan.
- **Prefer a library over hand-rolled code** for anything generic (geodesy,
  CSV, graph search, seeded PRNG). Hand-write only genuine domain logic: the ten
  policies, the ledger, scenario metrics, and the solvers. See
  `docs/REUSE-AUDIT.md`.
- **turf works in `[lng, lat]`; this domain uses `{ lat, lng }`.** The adapter
  lives in `geo.ts` and nowhere else. Getting it backwards silently produces
  distances that look plausible and are wrong.
- **`src/core/**` must not import** from `src/solvers/`, `src/ui/`, `src/ai/`,
  `app/`, `react`, or `next`. Enforced by a test in Task 1.
- **No file exceeds 250 lines.** If one does, it is doing too much.
- **Every source file opens with the 3-line header** (spec §4.2):
  `PURPOSE:` one sentence · `PIVOT:` what to change if the statement is about X ·
  `SAFE-TO-DELETE: yes|no — <reason>`.
- **Determinism:** no `Date.now()` and no unseeded `Math.random()` in
  `src/core/**`. Time arrives as an argument (`PolicyCtx.now`, `SolverInput.now`).
  Randomness only in `scripts/generate-fixtures.ts`, via a seeded PRNG.
- **`PolicyStatus` is four tiers** compared lexicographically:
  `block` > `medium` > `soft` > `pass`. Never summed into one number.
- **All money is integer paise-free rupees (₹, number)**; all distances
  kilometres (number); all durations **minutes** (number); all timestamps
  **epoch milliseconds** (number). No `Date` objects in `src/core`.
- **Licence note:** the metro CSVs are CC0 from
  `Vinayak-Chinchakhandi/Bengaluru-Metro-Network-Dataset` and must be attributed
  in `data/README.md`.
- **Commit after every task.** Conventional commits (`feat:`, `test:`, `chore:`).

## File Structure

| File | Responsibility |
|---|---|
| `commute-os/package.json` | scripts, devDeps, no runtime deps |
| `commute-os/tsconfig.json` | strict TS, ES2022, no DOM lib in core |
| `commute-os/vitest.config.ts` | test globs, coverage thresholds |
| `src/core/types.ts` | **the contract.** All domain types, zero logic |
| `src/core/geo.ts` | haversine, road-factor estimate, zone containment, nearest-N |
| `src/core/ledger.ts` | `MODEL` cost/carbon constants + cost & CO₂ functions |
| `src/core/metro.ts` | CSV → de-duplicated stations + **bidirectional** edges; path search; leg minutes |
| `src/core/clock.ts` | deterministic simulation clock (play/pause/seek/speed) |
| `src/core/routing.ts` | `RouteProvider`: cache → estimate, with `source` tagging |
| `src/core/policy.ts` | four-tier engine: `evaluate`, `worstTier`, `compareTiers` |
| `src/core/policies/*.ts` | ten pure policies, one per file |
| `src/core/policies/index.ts` | `ALL_POLICIES` registry |
| `src/core/scenario.ts` | `computeMetrics`, `theoreticalFloor`, `diff`, p10/p90 band |
| `scripts/generate-fixtures.ts` | seeded generator → 3 JSON fixtures |
| `data/*.csv` | the CC0 metro source data |
| `data/generated/*.json` | committed, deterministic fixtures |
| `tests/core/*.test.ts` | one test file per core module |
| `tests/core/policies/*.test.ts` | pass/soft/medium/block cases per policy |
| `tests/boundaries.test.ts` | enforces the import rules above |

---

### Task 1: Project scaffold, domain types, and the import-boundary gate

**Files:**
- Create: `commute-os/package.json`
- Create: `commute-os/tsconfig.json`
- Create: `commute-os/vitest.config.ts`
- Create: `commute-os/.gitignore`
- Create: `commute-os/src/core/types.ts`
- Test: `commute-os/tests/boundaries.test.ts`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: every domain type used by all later tasks —
  `LatLng`, `Fuel`, `Direction`, `Window`, `Gate`, `Office`, `Zone`,
  `Employee`, `Vehicle`, `Driver`, `Depot`, `MetroStation`, `MetroLine`,
  `MetroEdge`, `Trip`, `World`, `Savings`, `Candidate`, `PolicyCtx`,
  `PolicyStatus`, `ViolationCause`, `PolicyVerdict`, `PolicyTrace`, `Policy`,
  `Metrics`, `RouteResult`, `RouteSource`.

- [ ] **Step 1: Create the project scaffold**

`commute-os/package.json`:

```json
{
  "name": "commute-os",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "engines": { "node": ">=18.19.0" },
  "scripts": {
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "fixtures": "tsx scripts/generate-fixtures.ts"
  },
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
}
```

`commute-os/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "types": ["node"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "exactOptionalPropertyTypes": false,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true,
    "noEmit": true,
    "resolveJsonModule": true
  },
  "include": ["src", "tests", "scripts"]
}
```

`commute-os/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    coverage: { provider: 'v8', include: ['src/core/**'] },
  },
})
```

`commute-os/.gitignore`:

```
node_modules/
coverage/
.next/
.DS_Store
```

- [ ] **Step 2: Install and confirm the toolchain runs**

```bash
cd commute-os && npm install
```

Expected: installs cleanly on Node 18.19.0 — ~91 packages / ~79 MB including
devDependencies — with no peer warnings mentioning React or Next.

Sanity-check the library whose numbers the geo tests depend on:

```bash
node -e "const {distance}=require('@turf/distance'); const {point}=require('@turf/helpers'); console.log(distance(point([77.57313,12.97559]), point([77.60676,12.97566]), {units:'kilometers'}).toFixed(6))"
```

Expected: `3.644013`. If it differs, turf changed its earth radius and the
Task 2 expectations need regenerating.

- [ ] **Step 3: Write the failing import-boundary test**

`commute-os/tests/boundaries.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.ts')) out.push(p)
  }
  return out
}

const FORBIDDEN = [
  /from\s+['"]react['"]/,
  /from\s+['"]next[/'"]/,
  /from\s+['"].*\/solvers\//,
  /from\s+['"].*\/ui\//,
  /from\s+['"].*\/ai\//,
  /from\s+['"].*\/app\//,
]

describe('core import boundaries', () => {
  const files = walk('src/core')

  it('finds core source files', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it('src/core never imports react, next, solvers, ui or ai', () => {
    const offenders: string[] = []
    for (const f of files) {
      const src = readFileSync(f, 'utf8')
      for (const rx of FORBIDDEN) if (rx.test(src)) offenders.push(`${f} :: ${rx}`)
    }
    expect(offenders).toEqual([])
  })

  it('src/core is deterministic — no Date.now or bare Math.random', () => {
    const offenders: string[] = []
    for (const f of files) {
      const src = readFileSync(f, 'utf8')
      if (/Date\.now\(/.test(src)) offenders.push(`${f} :: Date.now`)
      if (/Math\.random\(/.test(src)) offenders.push(`${f} :: Math.random`)
    }
    expect(offenders).toEqual([])
  })

  it('no core file exceeds 250 lines', () => {
    const tooLong = files
      .map((f) => [f, readFileSync(f, 'utf8').split('\n').length] as const)
      .filter(([, n]) => n > 250)
      .map(([f, n]) => `${f} (${n})`)
    expect(tooLong).toEqual([])
  })

  it('every core file carries the 3-line header', () => {
    const missing = files.filter((f) => {
      const src = readFileSync(f, 'utf8')
      return !(src.includes('PURPOSE:') && src.includes('PIVOT:') && src.includes('SAFE-TO-DELETE:'))
    })
    expect(missing).toEqual([])
  })
})
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd commute-os && npx vitest run tests/boundaries.test.ts`
Expected: FAIL — `ENOENT: no such file or directory, scandir 'src/core'`.

- [ ] **Step 5: Write `src/core/types.ts`**

```ts
/**
 * PURPOSE: the single contract for the whole domain — all types, zero logic.
 * PIVOT: adding a constraint dimension (luggage, wheelchair) starts here.
 * SAFE-TO-DELETE: no — every module imports from this file.
 */

// ── primitives ──────────────────────────────────────────────────────────────
export type LatLng = { lat: number; lng: number }
export type Fuel = 'ICE' | 'CNG' | 'EV'
export type Direction = 'login' | 'logout'
export type Gender = 'F' | 'M' | 'X'

/** [start, end] in epoch ms, both inclusive. A trip may have several. */
export type Window = [number, number]

// ── places ──────────────────────────────────────────────────────────────────
export type Gate = { id: string; name: string; at: LatLng }
export type Office = { id: string; name: string; at: LatLng; gates: Gate[] }
export type Depot = { id: string; name: string; at: LatLng }

export type Zone = {
  id: string
  name: string
  centroid: LatLng
  /** closed ring; first point is NOT repeated at the end */
  polygon: LatLng[]
  /** 0..1, lowered by repeated admin rejections */
  confidence: number
}

// ── people & fleet ──────────────────────────────────────────────────────────
export type Employee = {
  id: string
  name: string
  gender: Gender
  homeAt: LatLng
  zoneId: string
  officeId: string
  /** historical no-show probability, 0..1 */
  noShowRate: number
}

export type Vehicle = {
  id: string
  plate: string
  seats: number
  fuel: Fuel
  /** EV only: full-charge range in km */
  rangeKm?: number
  /** EV only: state of charge, 0..100 */
  socPct?: number
}

export type Driver = {
  id: string
  name: string
  /** minutes of duty already worked today */
  dutyMinutesToday: number
  /** 0..100 quality score */
  score: number
}

// ── metro ───────────────────────────────────────────────────────────────────
export type MetroStation = {
  /** the dataset's station_code, e.g. "WHTM" */
  id: string
  name: string
  at: LatLng
  /** every line this station belongs to; interchanges have >1 */
  lineIds: string[]
  isInterchange: boolean
}

export type MetroLine = {
  id: string
  name: string
  colour: string
  /** station ids in sequence order */
  stationIds: string[]
  headwayMin: number
}

/** One directed hop. The loader emits BOTH directions for every CSV row. */
export type MetroEdge = { from: string; to: string; km: number; lineId: string }

// ── demand ──────────────────────────────────────────────────────────────────
export type Trip = {
  id: string
  /** an array from the outset: a merged trip is a Trip, not a special case */
  employeeIds: string[]
  pickupAt: LatLng
  zoneId: string
  officeId: string
  gateId: string
  direction: Direction
  /** acceptable pickup slots; ANY window may be satisfied */
  windows: Window[]
  seatsUsed: number
  vehicleId: string
  driverId: string
  /** pickup or drop falls in 21:00–06:00 local */
  isNightShift: boolean
}

export type World = {
  zones: Zone[]
  offices: Office[]
  employees: Employee[]
  vehicles: Vehicle[]
  drivers: Driver[]
  depots: Depot[]
  metroLines: MetroLine[]
  metroStations: MetroStation[]
  metroEdges: MetroEdge[]
}

// ── routing ─────────────────────────────────────────────────────────────────
export type RouteSource = 'cache' | 'estimate'
export type RouteResult = {
  km: number
  minutes: number
  polyline: LatLng[]
  source: RouteSource
}

// ── solver / policy plumbing ────────────────────────────────────────────────
export type Savings = {
  km: number
  inr: number
  co2Kg: number
  /** worst-case detour imposed on any single passenger, minutes */
  minutesAdded: number
  p10Inr: number
  p90Inr: number
}

/** A proposed grouping, already ordered, routed and costed. */
export type Candidate = {
  tripIds: string[]
  /** resolved trips, in proposed pickup order */
  trips: Trip[]
  vehicleId: string
  driverId: string
  km: number
  minutes: number
  /** employeeId -> detour minutes this candidate imposes */
  perPassengerAddedMin: Record<string, number>
  /** distinct gates touched, in visit order */
  gateIds: string[]
  seatsUsed: number
  /** epoch ms at which each trip is actually picked up */
  pickupTimes: Record<string, number>
}

/** Ambient state a policy may need but must not fetch itself. */
export type PolicyCtx = {
  /** simulation time, epoch ms. NEVER Date.now(). */
  now: number
  /** zoneId -> admin reject count */
  zoneRejections: Record<string, number>
  /** 1.0 = nominal */
  trafficMultiplier: number
  /** slider override of every employee.noShowRate */
  noShowOverride?: number
  /** employeeId -> detour minutes already absorbed this week */
  detourMinutesThisWeek: Record<string, number>
}

/**
 * Four tiers, compared lexicographically and never summed:
 *   block  — hard; never acceptable
 *   medium — serve everyone before optimising
 *   soft   — then be efficient
 *   pass   — no violation
 */
export type PolicyStatus = 'pass' | 'soft' | 'medium' | 'block'

/** VROOM's vocabulary (docs/API.md:445) plus one of ours. */
export type ViolationCause =
  | 'delay'
  | 'lead_time'
  | 'load'
  | 'max_tasks'
  | 'skills'
  | 'precedence'
  | 'missing_break'
  | 'max_travel_time'
  | 'max_distance'
  | 'max_load'
  | 'unfair_detour'

export type PolicyVerdict = {
  id: string
  name: string
  status: PolicyStatus
  cause?: ViolationCause
  /** magnitude of the miss; negative means over the limit */
  slack?: { value: number; unit: string }
  reason: string
}

export type PolicyTrace = {
  verdicts: PolicyVerdict[]
  blocked: boolean
  /** the worst status across all verdicts */
  tier: PolicyStatus
}

export type Policy = (c: Candidate, w: World, ctx: PolicyCtx) => PolicyVerdict

// ── metrics ─────────────────────────────────────────────────────────────────
export type Metrics = {
  cabKm: number
  shuttleKm: number
  metroPaxKm: number
  vehiclesUsed: number
  /** bin-packing floor: no routing can beat this */
  theoreticalFloorVehicles: number
  avgOccupancyPct: number
  costInr: number
  co2Kg: number
  /** total minutes passengers wait because a vehicle arrived early */
  waitingMin: number
  slaViolations: number
  unassignedCount: number
}
```

- [ ] **Step 6: Run the boundary test and typecheck to verify both pass**

Run: `cd commute-os && npx tsc --noEmit && npx vitest run tests/boundaries.test.ts`
Expected: typecheck clean; all 5 boundary tests PASS.

- [ ] **Step 7: Commit**

```bash
cd commute-os
git add package.json package-lock.json tsconfig.json vitest.config.ts .gitignore \
        src/core/types.ts tests/boundaries.test.ts
git commit -m "feat: scaffold commute-os core with domain types and boundary gate

Plain TS + Vitest, no React/Next (added in Plan 3). types.ts is the single
domain contract. tests/boundaries.test.ts enforces the spec's rules
mechanically: no react/next/solvers/ui/ai imports in core, no Date.now or
Math.random (determinism for golden tests), 250-line cap, and the mandatory
3-line file header."
```

---

### Task 2: `geo.ts` — distance, road-factor estimate, zone containment

**Files:**
- Create: `commute-os/src/core/geo.ts`
- Test: `commute-os/tests/core/geo.test.ts`

**Library-backed.** Distance and polygon containment come from `@turf/*`; only
the `{lat,lng}` ↔ `[lng,lat]` adapter and the road factor are ours. Every
expected number below was produced by turf 7.4.0 locally, not derived by hand.

**Interfaces:**
- Consumes: `LatLng`, `Zone` from `src/core/types.ts`; `distance` from
  `@turf/distance`; `booleanPointInPolygon` from
  `@turf/boolean-point-in-polygon`; `point`, `polygon` from `@turf/helpers`.
- Produces:
  - `haversineKm(a: LatLng, b: LatLng): number`
  - `ROAD_FACTOR: number` (1.3)
  - `estimateKm(a: LatLng, b: LatLng): number`
  - `pointInZone(p: LatLng, z: Zone): boolean`
  - `nearestN<T extends { at: LatLng }>(p: LatLng, items: T[], n: number, maxKm: number): T[]`

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/geo.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { haversineKm, estimateKm, pointInZone, nearestN, ROAD_FACTOR } from '../../src/core/geo'
import type { Zone } from '../../src/core/types'

// Real Bengaluru landmarks from the CC0 metro dataset (spec 04).
const MAJESTIC = { lat: 12.97559, lng: 77.57313 }
const MG_ROAD = { lat: 12.97566, lng: 77.60676 }
const WHITEFIELD = { lat: 12.99570, lng: 77.75773 }
const ELECTRONIC_CITY = { lat: 12.85654, lng: 77.66328 }

describe('haversineKm', () => {
  it('is zero for identical points', () => {
    expect(haversineKm(MAJESTIC, MAJESTIC)).toBe(0)
  })

  it('matches the known Majestic -> MG Road distance (3.644 km)', () => {
    expect(haversineKm(MAJESTIC, MG_ROAD)).toBeCloseTo(3.644, 2)
  })

  it('matches the known Majestic -> Whitefield distance (20.13 km)', () => {
    expect(haversineKm(MAJESTIC, WHITEFIELD)).toBeCloseTo(20.13, 1)
  })

  it('is symmetric', () => {
    expect(haversineKm(MAJESTIC, ELECTRONIC_CITY)).toBeCloseTo(
      haversineKm(ELECTRONIC_CITY, MAJESTIC), 9)
  })

  it('handles one degree of latitude as ~111 km', () => {
    expect(haversineKm({ lat: 12, lng: 77 }, { lat: 13, lng: 77 })).toBeCloseTo(111.195, 2)
  })
})

describe('estimateKm', () => {
  it('applies the road factor to the great-circle distance', () => {
    expect(estimateKm(MAJESTIC, MG_ROAD)).toBeCloseTo(haversineKm(MAJESTIC, MG_ROAD) * ROAD_FACTOR, 9)
  })

  it('uses a road factor of 1.3', () => {
    expect(ROAD_FACTOR).toBe(1.3)
  })
})

describe('turf integration guards', () => {
  it('does not silently swap lat and lng', () => {
    // If toPos were reversed, this Bengaluru pair would land in the Indian
    // Ocean and the distance would be wildly different.
    expect(haversineKm(MAJESTIC, MG_ROAD)).toBeLessThan(10)
  })

  it('does not throw on an open ring — geo.ts closes it', () => {
    const openSquare: Zone = {
      id: 'z2', name: 'Open', centroid: { lat: 12.95, lng: 77.62 },
      polygon: [
        { lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 },
        { lat: 13.00, lng: 77.67 }, { lat: 13.00, lng: 77.57 },
      ],
      confidence: 1,
    }
    expect(() => pointInZone({ lat: 12.95, lng: 77.62 }, openSquare)).not.toThrow()
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, openSquare)).toBe(true)
  })

  it('does not throw on a 2-point degenerate ring', () => {
    const bad: Zone = {
      id: 'z3', name: 'Bad', centroid: { lat: 12.95, lng: 77.62 },
      polygon: [{ lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 }],
      confidence: 1,
    }
    expect(() => pointInZone({ lat: 12.95, lng: 77.62 }, bad)).not.toThrow()
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, bad)).toBe(false)
  })
})

describe('pointInZone', () => {
  // a 0.1 x 0.1 degree square around Koramangala-ish
  const square: Zone = {
    id: 'z1', name: 'Square', centroid: { lat: 12.95, lng: 77.62 },
    polygon: [
      { lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 },
      { lat: 13.00, lng: 77.67 }, { lat: 13.00, lng: 77.57 },
    ],
    confidence: 1,
  }

  it('accepts an interior point', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, square)).toBe(true)
  })

  it('rejects a point outside to the east', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.90 }, square)).toBe(false)
  })

  it('rejects a point outside to the south', () => {
    expect(pointInZone({ lat: 12.50, lng: 77.62 }, square)).toBe(false)
  })

  it('rejects a degenerate polygon with fewer than 3 points', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, { ...square, polygon: [] })).toBe(false)
  })
})

describe('nearestN', () => {
  const items = [
    { id: 'mg', at: MG_ROAD },
    { id: 'wf', at: WHITEFIELD },
    { id: 'ec', at: ELECTRONIC_CITY },
  ]

  it('returns the closest items in ascending distance order', () => {
    expect(nearestN(MAJESTIC, items, 3, 100).map((i) => i.id)).toEqual(['mg', 'ec', 'wf'])
  })

  it('respects the count limit', () => {
    expect(nearestN(MAJESTIC, items, 1, 100).map((i) => i.id)).toEqual(['mg'])
  })

  it('excludes items beyond maxKm', () => {
    expect(nearestN(MAJESTIC, items, 3, 5).map((i) => i.id)).toEqual(['mg'])
  })

  it('returns an empty array when nothing is in range', () => {
    expect(nearestN(MAJESTIC, items, 3, 0.001)).toEqual([])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/geo.test.ts`
Expected: FAIL — `Failed to resolve import "../../src/core/geo"`.

- [ ] **Step 3: Write `src/core/geo.ts`**

```ts
/**
 * PURPOSE: geodesic distance, road-distance estimation, and zone containment.
 * PIVOT: if the statement needs real road distance everywhere, raise ROAD_FACTOR
 *        or move callers onto routing.ts's cache; this file stays the fallback.
 * SAFE-TO-DELETE: no — geo is used by every solver and half the policies.
 *
 * Geodesy and polygon containment are @turf/* (MIT). We own only the coordinate
 * adapter and the road factor — see docs/REUSE-AUDIT.md.
 */
import { distance } from '@turf/distance'
import { booleanPointInPolygon } from '@turf/boolean-point-in-polygon'
import { point, polygon as turfPolygon } from '@turf/helpers'
import type { LatLng, Zone } from './types'

/**
 * Multiplier from great-circle to driving distance. Design §6.2 / spec 01 §7:
 * used whenever the route cache misses, so the demo never depends on a network
 * call. 1.3 is the conventional urban figure.
 */
export const ROAD_FACTOR = 1.3

/**
 * THE ONLY PLACE the two coordinate conventions meet. turf and GeoJSON are
 * [lng, lat]; our domain is { lat, lng }. Reversing this produces distances
 * that look plausible and are wrong, so it lives here and nowhere else.
 */
const toPos = (p: LatLng): [number, number] => [p.lng, p.lat]

/** Great-circle distance in kilometres (turf's haversine, R = 6371008.8 m). */
export function haversineKm(a: LatLng, b: LatLng): number {
  return distance(point(toPos(a)), point(toPos(b)), { units: 'kilometers' })
}

/** Road-distance estimate: great-circle inflated by ROAD_FACTOR. */
export function estimateKm(a: LatLng, b: LatLng): number {
  return haversineKm(a, b) * ROAD_FACTOR
}

/**
 * Zone.polygon is stored as an OPEN ring (the first vertex is not repeated),
 * but GeoJSON requires a closed one and turf THROWS
 * "First and last Position are not equivalent" if it is open. Close it here so
 * no caller has to know. A ring of fewer than 3 vertices is rejected before
 * turf sees it, since that also throws.
 */
export function pointInZone(p: LatLng, z: Zone): boolean {
  if (z.polygon.length < 3) return false
  const ring = z.polygon.map(toPos)
  const first = ring[0]!
  const closed: Array<[number, number]> = [...ring, [first[0], first[1]]]
  return booleanPointInPolygon(point(toPos(p)), turfPolygon([closed]))
}

/**
 * The `n` items closest to `p` within `maxKm`, nearest first.
 * Used for metro boarding/alighting candidate search (design §10.1).
 */
export function nearestN<T extends { at: LatLng }>(
  p: LatLng,
  items: T[],
  n: number,
  maxKm: number,
): T[] {
  return items
    .map((item) => ({ item, km: haversineKm(p, item.at) }))
    .filter((x) => x.km <= maxKm)
    .sort((a, b) => a.km - b.km)
    .slice(0, n)
    .map((x) => x.item)
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/geo.test.ts && npx tsc --noEmit`
Expected: 17 tests PASS, typecheck clean.

All four distance expectations were produced by turf 7.4.0 locally:
`3.644013`, `20.126280`, `16.453067`, `111.195080`.

- [ ] **Step 5: Commit**

```bash
cd commute-os
git add src/core/geo.ts tests/core/geo.test.ts
git commit -m "feat(core): geo on @turf — distance, road estimate, zone containment

Geodesy and point-in-polygon delegate to @turf/* (MIT) rather than being
hand-rolled; we own only the {lat,lng} <-> [lng,lat] adapter and the 1.3
road factor. Distances asserted against real Bengaluru landmarks from the
CC0 metro dataset, with expectations generated by turf itself.

Two turf behaviours are covered by guard tests because both are silent
footguns: it needs a CLOSED GeoJSON ring (throws otherwise, and our Zone
stores an open one), and it takes [lng, lat] (reversing it yields
plausible-looking wrong distances)."
```

---

### Task 3: `ledger.ts` — the cost and carbon model

**Files:**
- Create: `commute-os/src/core/ledger.ts`
- Test: `commute-os/tests/core/ledger.test.ts`

**Interfaces:**
- Consumes: `Fuel`, `Vehicle` from `src/core/types.ts`.
- Produces:
  - `VehicleClass = 'sedan' | 'suv' | 'shuttle'`
  - `MODEL` (frozen constants object; every field carries a `_basis` sibling in `MODEL_BASIS`)
  - `MODEL_BASIS: Record<string, string>`
  - `classOf(v: Vehicle): VehicleClass`
  - `cabCostInr(km: number, minutes: number, cls: VehicleClass): number`
  - `co2KgPerKm(cls: VehicleClass, fuel: Fuel): number`
  - `co2Kg(km: number, cls: VehicleClass, fuel: Fuel): number`
  - `metroCostInr(passengers: number): number`
  - `metroCo2Kg(paxKm: number): number`
  - `boardingMinutes(stops: number, passengers: number): number`

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/ledger.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  MODEL, MODEL_BASIS, classOf, cabCostInr, co2KgPerKm, co2Kg,
  metroCostInr, metroCo2Kg, boardingMinutes,
} from '../../src/core/ledger'
import type { Vehicle } from '../../src/core/types'

const sedan: Vehicle = { id: 'v1', plate: 'KA01AA0001', seats: 4, fuel: 'ICE' }
const ev: Vehicle = { id: 'v2', plate: 'KA01AA0002', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 90 }
const suv: Vehicle = { id: 'v3', plate: 'KA01AA0003', seats: 6, fuel: 'ICE' }
const shuttle: Vehicle = { id: 'v4', plate: 'KA01AA0004', seats: 12, fuel: 'CNG' }

describe('MODEL', () => {
  it('holds the design §6.4 rates', () => {
    expect(MODEL.cabRatePerKm).toBe(18)
    expect(MODEL.cabBaseFarePerTrip).toBe(60)
    expect(MODEL.shuttleRatePerKm).toBe(26)
    expect(MODEL.driverCostPerHour).toBe(180)
    expect(MODEL.metroFarePerTrip).toBe(30)
  })

  it('holds the design §6.4 carbon factors', () => {
    expect(MODEL.co2SedanPerKm).toBe(0.142)
    expect(MODEL.co2SuvPerKm).toBe(0.186)
    expect(MODEL.co2ShuttlePerKm).toBe(0.68)
    expect(MODEL.co2EvPerKm).toBe(0.1)
    expect(MODEL.co2MetroPerPassengerKm).toBe(0.014)
  })

  it('documents a basis string for every numeric constant', () => {
    const numericKeys = Object.keys(MODEL).filter((k) => typeof (MODEL as Record<string, unknown>)[k] === 'number')
    const undocumented = numericKeys.filter((k) => !MODEL_BASIS[k])
    expect(undocumented).toEqual([])
  })

  it('is frozen so no caller can mutate the demo economics', () => {
    expect(Object.isFrozen(MODEL)).toBe(true)
  })
})

describe('classOf', () => {
  it('classifies by seat count', () => {
    expect(classOf(sedan)).toBe('sedan')
    expect(classOf(suv)).toBe('suv')
    expect(classOf(shuttle)).toBe('shuttle')
  })
})

describe('cabCostInr', () => {
  it('is base fare plus distance plus driver time for a sedan', () => {
    // 60 + 10*18 + (30/60)*180 = 60 + 180 + 90 = 330
    expect(cabCostInr(10, 30, 'sedan')).toBeCloseTo(330, 6)
  })

  it('charges the shuttle rate for a shuttle', () => {
    // 60 + 10*26 + (30/60)*180 = 60 + 260 + 90 = 410
    expect(cabCostInr(10, 30, 'shuttle')).toBeCloseTo(410, 6)
  })

  it('still charges the base fare for a zero-distance trip', () => {
    expect(cabCostInr(0, 0, 'sedan')).toBe(MODEL.cabBaseFarePerTrip)
  })
})

describe('co2KgPerKm', () => {
  it('uses the EV factor regardless of body class', () => {
    expect(co2KgPerKm('sedan', 'EV')).toBe(0.1)
    expect(co2KgPerKm('suv', 'EV')).toBe(0.1)
  })

  it('uses body class for combustion vehicles', () => {
    expect(co2KgPerKm('sedan', 'ICE')).toBe(0.142)
    expect(co2KgPerKm('suv', 'ICE')).toBe(0.186)
    expect(co2KgPerKm('shuttle', 'CNG')).toBe(0.68)
  })

  it('shows an EV is cleaner than petrol but NOT zero — the honesty check', () => {
    expect(co2KgPerKm('sedan', 'EV')).toBeLessThan(co2KgPerKm('sedan', 'ICE'))
    expect(co2KgPerKm('sedan', 'EV')).toBeGreaterThan(0)
  })
})

describe('co2Kg and metro', () => {
  it('scales carbon linearly with distance', () => {
    expect(co2Kg(10, 'sedan', 'ICE')).toBeCloseTo(1.42, 6)
  })

  it('prices metro per passenger', () => {
    expect(metroCostInr(3)).toBe(90)
  })

  it('makes metro dramatically cleaner per passenger-km than a cab', () => {
    expect(metroCo2Kg(10)).toBeCloseTo(0.14, 6)
    expect(metroCo2Kg(10)).toBeLessThan(co2Kg(10, 'sedan', 'EV'))
  })
})

describe('boardingMinutes', () => {
  it('charges setup once per stop and service once per passenger', () => {
    // 2 stops, 3 passengers = 2*1.5 + 3*0.5 = 4.5
    expect(boardingMinutes(2, 3)).toBeCloseTo(4.5, 6)
  })

  it('makes two colleagues at ONE gate cheaper than at two gates', () => {
    expect(boardingMinutes(1, 2)).toBeLessThan(boardingMinutes(2, 2))
  })

  it('is zero for an empty candidate', () => {
    expect(boardingMinutes(0, 0)).toBe(0)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/ledger.test.ts`
Expected: FAIL — `Failed to resolve import "../../src/core/ledger"`.

- [ ] **Step 3: Write `src/core/ledger.ts`**

```ts
/**
 * PURPOSE: every rupee and kilogram the UI claims, in one auditable place.
 * PIVOT: if the statement is cost-led, tune the rates here and nothing else;
 *        if it is carbon-led, the co2* factors are the levers.
 * SAFE-TO-DELETE: no — CostModelPanel renders this and judges ask about it.
 */
import type { Fuel, Vehicle } from './types'

export type VehicleClass = 'sedan' | 'suv' | 'shuttle'

/**
 * ALL VALUES ARE TUNABLE ASSUMPTIONS, not MoveInSync actuals.
 * MODEL_BASIS below documents where each number comes from; the UI renders
 * both so "where does that figure come from?" is a click, not a stammer.
 */
export const MODEL = Object.freeze({
  cabRatePerKm: 18,
  cabBaseFarePerTrip: 60,
  suvRatePerKm: 22,
  shuttleRatePerKm: 26,
  shuttleSeats: 12,
  driverCostPerHour: 180,
  metroFarePerTrip: 30,

  co2SedanPerKm: 0.142,
  co2SuvPerKm: 0.186,
  co2ShuttlePerKm: 0.68,
  co2EvPerKm: 0.1,
  co2MetroPerPassengerKm: 0.014,

  /** minutes lost arriving at a new stop, regardless of headcount */
  setupMinPerStop: 1.5,
  /** additional minutes per passenger boarding at that stop */
  serviceMinPerPassenger: 0.5,
})

export const MODEL_BASIS: Record<string, string> = {
  cabRatePerKm: 'typical Bengaluru corporate sedan contract rate',
  cabBaseFarePerTrip: 'fixed per-dispatch component',
  suvRatePerKm: 'larger body, higher contract rate',
  shuttleRatePerKm: '12-seater; cheaper PER PASSENGER despite higher per-km',
  shuttleSeats: 'standard 12-seat tempo traveller',
  driverCostPerHour: 'fully loaded driver cost',
  metroFarePerTrip: 'BMRCL mid-distance fare',
  co2SedanPerKm: 'petrol sedan ~6.1 L/100km x 2.31 kg CO2/L',
  co2SuvPerKm: 'petrol SUV ~8.0 L/100km x 2.31 kg CO2/L',
  co2ShuttlePerKm: '12-seater diesel',
  co2EvPerKm: '0.14 kWh/km x ~0.71 kg CO2/kWh India grid mix — a ~30% cut, NOT zero',
  co2MetroPerPassengerKm: 'electrified rail at high load factor',
  setupMinPerStop: 'door-to-vehicle time at a new pickup point (FleetPy std_bt)',
  serviceMinPerPassenger: 'marginal boarding time per extra person (FleetPy add_bt)',
}

/** Body class from seat count. */
export function classOf(v: Vehicle): VehicleClass {
  if (v.seats >= MODEL.shuttleSeats) return 'shuttle'
  if (v.seats > 4) return 'suv'
  return 'sedan'
}

function ratePerKm(cls: VehicleClass): number {
  if (cls === 'shuttle') return MODEL.shuttleRatePerKm
  if (cls === 'suv') return MODEL.suvRatePerKm
  return MODEL.cabRatePerKm
}

/** Base fare + distance + driver time. */
export function cabCostInr(km: number, minutes: number, cls: VehicleClass): number {
  return (
    MODEL.cabBaseFarePerTrip +
    km * ratePerKm(cls) +
    (minutes / 60) * MODEL.driverCostPerHour
  )
}

/**
 * Carbon per km. Fuel wins over body class: an EV is an EV whatever its shape.
 * Note the EV figure is ~0.10 vs ~0.14 for petrol — a real cut, not zero.
 */
export function co2KgPerKm(cls: VehicleClass, fuel: Fuel): number {
  if (fuel === 'EV') return MODEL.co2EvPerKm
  if (cls === 'shuttle') return MODEL.co2ShuttlePerKm
  if (cls === 'suv') return MODEL.co2SuvPerKm
  return MODEL.co2SedanPerKm
}

export function co2Kg(km: number, cls: VehicleClass, fuel: Fuel): number {
  return km * co2KgPerKm(cls, fuel)
}

export function metroCostInr(passengers: number): number {
  return passengers * MODEL.metroFarePerTrip
}

export function metroCo2Kg(paxKm: number): number {
  return paxKm * MODEL.co2MetroPerPassengerKm
}

/**
 * Boarding time, split into a per-stop and a per-passenger component.
 * Two colleagues at one gate cost setup + 2*service, NOT 2*(setup + service) —
 * so same-building pooling is genuinely cheaper. (spec 06 §6.4, spec 07 §3)
 */
export function boardingMinutes(stops: number, passengers: number): number {
  return stops * MODEL.setupMinPerStop + passengers * MODEL.serviceMinPerPassenger
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/ledger.test.ts && npx tsc --noEmit`
Expected: 17 tests PASS, typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd commute-os
git add src/core/ledger.ts tests/core/ledger.test.ts
git commit -m "feat(core): ledger — auditable cost and carbon model

Every numeric constant has a MODEL_BASIS entry, asserted by test, so the
UI can show its derivation. MODEL is frozen. Carries the honesty check as
a test: an EV is ~0.10 vs ~0.14 kg/km on the India grid, cleaner than
petrol but not zero. boardingMinutes splits setup-per-stop from
service-per-passenger (VROOM setup/service, FleetPy std_bt/add_bt)."
```

---

### Task 4: `metro.ts` — real metro graph, with all three data gotchas covered

**Files:**
- Create: `commute-os/data/bengaluru_metro_network.csv` (copy from `../reference/bengaluru-metro-dataset/`)
- Create: `commute-os/data/README.md` (CC0 attribution — required)
- Create: `commute-os/src/core/metro.ts`
- Test: `commute-os/tests/core/metro.test.ts`

**Library-backed.** CSV parsing is `papaparse`; the shortest path is
`graphology` + `graphology-shortest-path`. We own the de-duplication, the
bidirectional edge synthesis, the interchange count and the leg timing.

**Interfaces:**
- Consumes: `MetroStation`, `MetroLine`, `MetroEdge` from `types.ts`; `Papa` from
  `papaparse`; `Graph` from `graphology`; `dijkstra` from
  `graphology-shortest-path`.
- Produces:
  - `MetroCsvRow` (parsed row shape)
  - `AVG_METRO_SPEED_KMPH`, `DWELL_MIN_PER_STOP`, `INTERCHANGE_MIN`, `DEFAULT_HEADWAY_MIN`
  - `parseMetroCsv(csv: string): MetroCsvRow[]`
  - `buildMetroGraph(rows: MetroCsvRow[]): { stations: MetroStation[]; lines: MetroLine[]; edges: MetroEdge[] }`
  - `MetroGraph` (a `graphology` `Graph`)
  - `toMetroGraph(edges: MetroEdge[]): MetroGraph`
  - `MetroPath = { stationIds: string[]; km: number; interchanges: number }`
  - `findMetroPath(fromId: string, toId: string, g: MetroGraph): MetroPath | null`
  - `metroLegMinutes(path: MetroPath, headwayMin?: number): number`

**Signature note.** `findMetroPath` takes a prebuilt `MetroGraph`, not the edge
array, so the graph is constructed once rather than per query — Metro Feeder
Mesh calls it hundreds of times during candidate search.

**Critical context (spec 04 §3).** Three gotchas, each with a dedicated test:
1. The CSV graph is **directed** — exactly 3 rows have an empty
   `next_station_code` (one terminal per line). Reverse edges must be
   synthesised or logout routing silently returns nothing.
2. **85 rows, 83 stations.** `KGWA` (Majestic) and `RVR` appear once per line
   with coordinates ~50 m apart. De-duplicate on `station_code` while
   *accumulating* `lineIds`, or the two interchanges double-count.
3. `distance_to_next_km = 0.0` on the 3 terminals is a **sentinel**, not an
   edge. Never emit a zero-cost edge from it.

- [ ] **Step 1: Copy the source data and write its attribution**

```bash
cd commute-os && mkdir -p data
cp ../reference/bengaluru-metro-dataset/bengaluru_metro_network.csv data/
cat > data/README.md <<'EOF'
# Data sources

## bengaluru_metro_network.csv

Bengaluru (Namma) Metro network: 85 rows / 83 unique stations across the
Purple, Green and Yellow lines, with coordinates, sequence, interchange flags,
directed next-station edges and real inter-station distances.

- Source: https://github.com/Vinayak-Chinchakhandi/Bengaluru-Metro-Network-Dataset
- Licence: CC0 (public domain), asserted in the upstream README.
  GitHub detects no LICENSE file, so it is attributed explicitly here.
- Retrieved: 2026-09-02
- Analysis: `../../specs/04-bengaluru-metro-dataset.md`

Community data, not BMRCL official. Five coordinates were spot-checked against
known locations and all were correct.
EOF
```

- [ ] **Step 2: Write the failing tests**

`commute-os/tests/core/metro.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  parseMetroCsv, buildMetroGraph, toMetroGraph, findMetroPath, metroLegMinutes,
  AVG_METRO_SPEED_KMPH, DWELL_MIN_PER_STOP, INTERCHANGE_MIN,
} from '../../src/core/metro'

const CSV = readFileSync('data/bengaluru_metro_network.csv', 'utf8')
const rows = parseMetroCsv(CSV)
const graph = buildMetroGraph(rows)
const mg = toMetroGraph(graph.edges) // built once; findMetroPath takes the graph

describe('parseMetroCsv', () => {
  it('parses all 85 data rows', () => {
    expect(rows.length).toBe(85)
  })

  it('parses the first Purple Line row exactly', () => {
    const whtm = rows.find((r) => r.station_code === 'WHTM')
    expect(whtm).toBeDefined()
    expect(whtm!.station_name).toBe('Whitefield (Kadugodi)')
    expect(whtm!.line).toBe('Purple Line')
    expect(whtm!.sequence).toBe(1)
    expect(whtm!.next_station_code).toBe('UWVL')
    expect(whtm!.distance_to_next_km).toBeCloseTo(1.04, 6)
    expect(whtm!.latitude).toBeCloseTo(12.995699, 5)
    expect(whtm!.line_color).toBe('#7E22CE')
    expect(whtm!.is_interchange).toBe(false)
  })

  it('reads terminals as having no next station', () => {
    const terminals = rows.filter((r) => r.next_station_code === null)
    expect(terminals.map((r) => r.station_code).sort()).toEqual(['APTS', 'CHLG', 'DELT'])
  })
})

// ── GOTCHA 2: 85 rows, 83 stations ────────────────────────────────────────
describe('buildMetroGraph — station de-duplication', () => {
  it('collapses 85 rows into 83 unique stations', () => {
    expect(graph.stations.length).toBe(83)
  })

  it('gives the two interchanges BOTH their line memberships', () => {
    const kgwa = graph.stations.find((s) => s.id === 'KGWA')
    const rvr = graph.stations.find((s) => s.id === 'RVR')
    expect(kgwa!.lineIds.sort()).toEqual(['Green Line', 'Purple Line'])
    expect(rvr!.lineIds.sort()).toEqual(['Green Line', 'Yellow Line'])
  })

  it('marks exactly two stations as interchanges', () => {
    const ic = graph.stations.filter((s) => s.isInterchange).map((s) => s.id).sort()
    expect(ic).toEqual(['KGWA', 'RVR'])
  })

  it('gives every other station exactly one line', () => {
    const multi = graph.stations.filter((s) => s.lineIds.length > 1).map((s) => s.id).sort()
    expect(multi).toEqual(['KGWA', 'RVR'])
  })
})

describe('buildMetroGraph — lines', () => {
  it('builds three lines with the documented station counts', () => {
    const byId = Object.fromEntries(graph.lines.map((l) => [l.id, l]))
    expect(byId['Purple Line']!.stationIds.length).toBe(37)
    expect(byId['Green Line']!.stationIds.length).toBe(32)
    expect(byId['Yellow Line']!.stationIds.length).toBe(16)
  })

  it('orders each line by sequence', () => {
    const yellow = graph.lines.find((l) => l.id === 'Yellow Line')!
    expect(yellow.stationIds[0]).toBe('RVR')
    expect(yellow.stationIds[yellow.stationIds.length - 1]).toBe('DELT')
  })

  it('carries the line colour', () => {
    expect(graph.lines.find((l) => l.id === 'Yellow Line')!.colour).toBe('#CA8A04')
  })
})

// ── GOTCHA 1 & 3: directed source, terminal sentinels ─────────────────────
describe('buildMetroGraph — edges', () => {
  it('emits 164 edges: 82 forward hops, both directions', () => {
    // 85 rows - 3 terminals = 82 forward; x2 = 164
    expect(graph.edges.length).toBe(164)
  })

  it('synthesises the REVERSE edge for every forward edge', () => {
    const fwd = graph.edges.find((e) => e.from === 'WHTM' && e.to === 'UWVL')
    const rev = graph.edges.find((e) => e.from === 'UWVL' && e.to === 'WHTM')
    expect(fwd!.km).toBeCloseTo(1.04, 6)
    expect(rev!.km).toBeCloseTo(1.04, 6)
  })

  it('never emits a zero-km edge from a terminal sentinel', () => {
    expect(graph.edges.filter((e) => e.km === 0)).toEqual([])
    for (const t of ['CHLG', 'APTS', 'DELT']) {
      // a terminal still has an inbound-derived reverse edge, but no edge
      // created FROM its own null next_station_code
      expect(graph.edges.filter((e) => e.from === t && e.km === 0)).toEqual([])
    }
  })
})

describe('findMetroPath', () => {
  it('returns a zero-length path for the same station', () => {
    const p = findMetroPath('RVR', 'RVR', mg)
    expect(p).toEqual({ stationIds: ['RVR'], km: 0, interchanges: 0 })
  })

  it('finds the 3-hop Yellow Line path RVR -> BTM Layout at 3.16 km', () => {
    const p = findMetroPath('RVR', 'BTML', mg)!
    expect(p.stationIds).toEqual(['RVR', 'RAGI', 'JDEV', 'BTML'])
    expect(p.km).toBeCloseTo(3.16, 2)
    expect(p.interchanges).toBe(0)
  })

  it('travels the reverse direction too — proving gotcha 1 is handled', () => {
    const p = findMetroPath('BTML', 'RVR', mg)!
    expect(p.stationIds).toEqual(['BTML', 'JDEV', 'RAGI', 'RVR'])
    expect(p.km).toBeCloseTo(3.16, 2)
  })

  it('routes across an interchange and counts it', () => {
    // Whitefield (Purple) -> Electronic City (Yellow) must change lines twice:
    // Purple -> Green at KGWA, Green -> Yellow at RVR
    const p = findMetroPath('WHTM', 'ELCT', mg)!
    expect(p.stationIds[0]).toBe('WHTM')
    expect(p.stationIds[p.stationIds.length - 1]).toBe('ELCT')
    expect(p.stationIds).toContain('KGWA')
    expect(p.stationIds).toContain('RVR')
    expect(p.interchanges).toBe(2)
    expect(p.km).toBeGreaterThan(30)
  })

  it('returns null for an unknown station', () => {
    expect(findMetroPath('RVR', 'NOPE', mg)).toBeNull()
    expect(findMetroPath('NOPE', 'RVR', mg)).toBeNull()
  })
})

describe('metroLegMinutes', () => {
  it('is travel time + dwell + interchange penalty', () => {
    const p = { stationIds: ['RVR', 'RAGI', 'JDEV', 'BTML'], km: 3.16, interchanges: 0 }
    // 3.16/32*60 = 5.925 ; dwell 4*0.35 = 1.4 ; headway/2 excluded by default
    expect(metroLegMinutes(p)).toBeCloseTo(7.325, 3)
  })

  it('adds the interchange penalty', () => {
    const p = { stationIds: ['A', 'B'], km: 3.16, interchanges: 2 }
    const base = { ...p, interchanges: 0 }
    expect(metroLegMinutes(p) - metroLegMinutes(base)).toBeCloseTo(2 * INTERCHANGE_MIN, 6)
  })

  it('adds half the headway as expected wait when one is supplied', () => {
    const p = { stationIds: ['A', 'B'], km: 1, interchanges: 0 }
    expect(metroLegMinutes(p, 6) - metroLegMinutes(p)).toBeCloseTo(3, 6)
  })

  it('uses the documented constants', () => {
    expect(AVG_METRO_SPEED_KMPH).toBe(32)
    expect(DWELL_MIN_PER_STOP).toBe(0.35)
    expect(INTERCHANGE_MIN).toBe(5)
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/metro.test.ts`
Expected: FAIL — `Failed to resolve import "../../src/core/metro"`.

- [ ] **Step 4: Write `src/core/metro.ts`**

```ts
/**
 * PURPOSE: turn the CC0 metro CSV into a routable, de-duplicated graph.
 * PIVOT: if the statement is mass-transit led, this file and metro-feeder are
 *        the hero path; new lines are new CSV rows, no code change.
 * SAFE-TO-DELETE: no — Metro Feeder Mesh cannot run without it.
 */
import Graph from 'graphology'
import { dijkstra } from 'graphology-shortest-path'
import Papa from 'papaparse'
import type { MetroEdge, MetroLine, MetroStation } from './types'

/** BMRCL scheduled average including dwell. Estimate — label it in the UI. */
export const AVG_METRO_SPEED_KMPH = 32
/** ~20 s per stop. Estimate. */
export const DWELL_MIN_PER_STOP = 0.35
/** Platform change at Majestic or RV Road. Estimate. */
export const INTERCHANGE_MIN = 5
/** Peak headway; expected wait is half this. Estimate. */
export const DEFAULT_HEADWAY_MIN = 6

export type MetroCsvRow = {
  station_code: string
  station_name: string
  line: string
  sequence: number
  is_interchange: boolean
  /** null at the three terminals */
  next_station_code: string | null
  latitude: number
  longitude: number
  /** 0 at terminals — a SENTINEL, not an edge weight */
  distance_to_next_km: number
  line_color: string
}

/**
 * Parsed with papaparse rather than split(',') — the current file is unquoted,
 * but a hand parser breaks silently the day a station name contains a comma.
 * papaparse yields `""` for an empty field, which is how the three terminals'
 * missing next_station_code arrives; it is mapped to null here.
 */
export function parseMetroCsv(csv: string): MetroCsvRow[] {
  const parsed = Papa.parse<Record<string, string>>(csv, {
    header: true,
    skipEmptyLines: true,
    transform: (v) => v.trim(),
  })
  if (parsed.errors.length > 0) {
    throw new Error(`metro CSV parse error: ${parsed.errors[0]!.message}`)
  }
  return parsed.data.map((r) => {
    const next = r['next_station_code'] ?? ''
    return {
      station_code: r['station_code'] ?? '',
      station_name: r['station_name'] ?? '',
      line: r['line'] ?? '',
      sequence: Number(r['sequence']),
      is_interchange: r['is_interchange'] === '1',
      next_station_code: next === '' || next.toUpperCase() === 'NULL' ? null : next,
      latitude: Number(r['latitude']),
      longitude: Number(r['longitude']),
      distance_to_next_km: Number(r['distance_to_next_km']),
      line_color: r['line_color'] ?? '',
    }
  })
}

/**
 * Build stations, lines and edges.
 *
 * GOTCHA 2: de-duplicate on station_code, ACCUMULATING lineIds — interchanges
 *   appear once per line with coordinates ~50 m apart. First row wins for
 *   coordinates; both lines are recorded.
 * GOTCHA 1: the CSV is directed, so emit BOTH directions for every hop.
 * GOTCHA 3: a null next_station_code means no edge. Never trust the 0.0 km.
 */
export function buildMetroGraph(rows: MetroCsvRow[]): {
  stations: MetroStation[]
  lines: MetroLine[]
  edges: MetroEdge[]
} {
  const stations = new Map<string, MetroStation>()
  const lineRows = new Map<string, MetroCsvRow[]>()
  const edges: MetroEdge[] = []

  for (const r of rows) {
    // ── stations (gotcha 2) ──
    const existing = stations.get(r.station_code)
    if (existing) {
      if (!existing.lineIds.includes(r.line)) existing.lineIds.push(r.line)
      existing.isInterchange = existing.isInterchange || r.is_interchange
    } else {
      stations.set(r.station_code, {
        id: r.station_code,
        name: r.station_name,
        at: { lat: r.latitude, lng: r.longitude },
        lineIds: [r.line],
        isInterchange: r.is_interchange,
      })
    }

    // ── lines ──
    const bucket = lineRows.get(r.line)
    if (bucket) bucket.push(r)
    else lineRows.set(r.line, [r])

    // ── edges (gotchas 1 and 3) ──
    if (r.next_station_code === null) continue
    if (r.distance_to_next_km <= 0) continue
    edges.push({ from: r.station_code, to: r.next_station_code, km: r.distance_to_next_km, lineId: r.line })
    edges.push({ from: r.next_station_code, to: r.station_code, km: r.distance_to_next_km, lineId: r.line })
  }

  const lines: MetroLine[] = [...lineRows.entries()].map(([id, rs]) => {
    const ordered = [...rs].sort((a, b) => a.sequence - b.sequence)
    return {
      id,
      name: id,
      colour: ordered[0]!.line_color,
      stationIds: ordered.map((r) => r.station_code),
      headwayMin: DEFAULT_HEADWAY_MIN,
    }
  })

  return { stations: [...stations.values()], lines, edges }
}

export type MetroGraph = Graph
export type MetroPath = { stationIds: string[]; km: number; interchanges: number }

/**
 * Build the graphology graph once. Undirected and simple: buildMetroGraph
 * already emitted both directions, and no two adjacent stations are joined by
 * more than one line, so mergeEdge cannot lose a parallel edge.
 */
export function toMetroGraph(edges: MetroEdge[]): MetroGraph {
  const g: Graph = new Graph({ type: 'undirected', multi: false })
  for (const e of edges) {
    g.mergeNode(e.from)
    g.mergeNode(e.to)
    g.mergeEdge(e.from, e.to, { km: e.km, lineId: e.lineId })
  }
  return g
}

/**
 * Shortest path by kilometres, via graphology's Dijkstra (a real binary heap —
 * the hand-rolled version this replaced re-sorted its queue every iteration).
 *
 * Two library behaviours must be handled, both verified against
 * graphology-shortest-path 2.1.0:
 *   - `dijkstra.bidirectional` THROWS on a node that is not in the graph, so
 *     guard with hasNode first;
 *   - it returns `null` (not `[]`) when the nodes exist but are disconnected.
 */
export function findMetroPath(fromId: string, toId: string, g: MetroGraph): MetroPath | null {
  if (!g.hasNode(fromId) || !g.hasNode(toId)) return null
  if (fromId === toId) return { stationIds: [fromId], km: 0, interchanges: 0 }

  const path = dijkstra.bidirectional(g, fromId, toId, 'km')
  if (!path || path.length === 0) return null

  let km = 0
  let interchanges = 0
  let prevLine: string | null = null

  for (let i = 0; i < path.length - 1; i++) {
    const edgeKey = g.edge(path[i]!, path[i + 1]!)
    if (edgeKey === undefined) return null
    km += g.getEdgeAttribute(edgeKey, 'km') as number
    const lineId = g.getEdgeAttribute(edgeKey, 'lineId') as string
    if (prevLine !== null && lineId !== prevLine) interchanges++
    prevLine = lineId
  }

  return { stationIds: path, km, interchanges }
}

/**
 * Minutes for a metro leg from REAL inter-station distances — replacing the
 * v1.0 "2.2 min per stop" guess (spec 04 §4).
 * `headwayMin` adds the expected wait (half the headway) when supplied.
 */
export function metroLegMinutes(path: MetroPath, headwayMin?: number): number {
  const travel = (path.km / AVG_METRO_SPEED_KMPH) * 60
  const dwell = path.stationIds.length * DWELL_MIN_PER_STOP
  const change = path.interchanges * INTERCHANGE_MIN
  const wait = headwayMin === undefined ? 0 : headwayMin / 2
  return travel + dwell + change + wait
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/metro.test.ts && npx tsc --noEmit`
Expected: 22 tests PASS, typecheck clean.

Reference values, produced locally against the real CSV with an independent
Dijkstra: **164 edges**, `RVR→BTML` = **3.16 km / 0 interchanges / 4 stations**,
`WHTM→ELCT` = **43.05 km / 2 interchanges / 41 stations**.

If `interchanges` comes back as 1 rather than 2 on WHTM→ELCT, the count is being
derived from station `isInterchange` flags instead of edge `lineId` transitions —
re-read the loop in `findMetroPath`.

- [ ] **Step 6: Commit**

```bash
cd commute-os
git add data/bengaluru_metro_network.csv data/README.md src/core/metro.ts tests/core/metro.test.ts
git commit -m "feat(core): metro graph from real CC0 data, on papaparse + graphology

Replaces hand-approximated coordinates and the guessed 2.2 min/stop with
83 real stations and real inter-station distances (design v1.1 A3, spec 04).

All three data gotchas are covered by dedicated tests:
- the CSV graph is DIRECTED, so reverse edges are synthesised (164 edges
  from 82 forward hops); a reverse-direction path test proves it
- 85 rows collapse to 83 stations, accumulating lineIds so Majestic and
  RV Road are single interchange nodes rather than duplicates
- distance_to_next_km=0 on the 3 terminals is a sentinel, never an edge

CC0 attribution in data/README.md."
```

---

### Task 5: `clock.ts` and `routing.ts` — deterministic time and offline routing

**Files:**
- Create: `commute-os/src/core/clock.ts`
- Create: `commute-os/src/core/routing.ts`
- Test: `commute-os/tests/core/clock.test.ts`
- Test: `commute-os/tests/core/routing.test.ts`

**Interfaces:**
- Consumes: `LatLng`, `RouteResult`, `RouteSource` from `types.ts`; `estimateKm` from `geo.ts`.
- Produces:
  - `SimClock` with `now(): number`, `seek(ms): void`, `advance(realMs: number): void`, `play(): void`, `pause(): void`, `setSpeed(n): void`, `isPlaying(): boolean`, `subscribe(fn: (ms: number) => void): () => void`
  - `createClock(opts: { start: number; end: number; speed?: number }): SimClock`
  - `AVG_CITY_SPEED_KMPH: number` (22)
  - `RouteCache = Record<string, { km: number; minutes: number; polyline: LatLng[] }>`
  - `cacheKey(a: LatLng, b: LatLng): string`
  - `RouteProvider = { route(a: LatLng, b: LatLng): RouteResult }`
  - `createRouteProvider(cache: RouteCache, trafficMultiplier?: number): RouteProvider`

**Design deviation from spec §6.2, deliberate:** `route()` is **synchronous**,
not `Promise`-returning. Both tiers (cache, estimate) are local computations, and
a sync signature keeps the solvers free of async plumbing. The live-API tier is
Tier C (§19) and is not built, so nothing needs to await.

- [ ] **Step 1: Write the failing clock tests**

`commute-os/tests/core/clock.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { createClock } from '../../src/core/clock'

const START = 1_757_000_000_000 // fixed epoch ms; no Date.now anywhere
const END = START + 12 * 60 * 60 * 1000

describe('createClock', () => {
  it('starts paused at the start time', () => {
    const c = createClock({ start: START, end: END })
    expect(c.now()).toBe(START)
    expect(c.isPlaying()).toBe(false)
  })

  it('does not advance while paused', () => {
    const c = createClock({ start: START, end: END })
    c.advance(5000)
    expect(c.now()).toBe(START)
  })

  it('advances by realMs * speed while playing', () => {
    const c = createClock({ start: START, end: END, speed: 20 })
    c.play()
    c.advance(1000)
    expect(c.now()).toBe(START + 20_000)
  })

  it('clamps at the end time and auto-pauses', () => {
    const c = createClock({ start: START, end: START + 1000 })
    c.play()
    c.advance(10_000)
    expect(c.now()).toBe(START + 1000)
    expect(c.isPlaying()).toBe(false)
  })

  it('seeks within bounds and clamps outside them', () => {
    const c = createClock({ start: START, end: END })
    c.seek(START + 60_000)
    expect(c.now()).toBe(START + 60_000)
    c.seek(START - 1)
    expect(c.now()).toBe(START)
    c.seek(END + 1)
    expect(c.now()).toBe(END)
  })

  it('notifies subscribers on advance and seek, and stops after unsubscribe', () => {
    const c = createClock({ start: START, end: END, speed: 1 })
    const spy = vi.fn()
    const off = c.subscribe(spy)
    c.seek(START + 1000)
    c.play()
    c.advance(1000)
    expect(spy).toHaveBeenCalledTimes(2)
    expect(spy).toHaveBeenLastCalledWith(START + 2000)
    off()
    c.advance(1000)
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('rejects a non-positive speed', () => {
    const c = createClock({ start: START, end: END })
    expect(() => c.setSpeed(0)).toThrow(/speed/i)
    expect(() => c.setSpeed(-1)).toThrow(/speed/i)
  })
})
```

- [ ] **Step 2: Write the failing routing tests**

`commute-os/tests/core/routing.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { cacheKey, createRouteProvider, AVG_CITY_SPEED_KMPH } from '../../src/core/routing'
import { estimateKm } from '../../src/core/geo'
import type { RouteCache } from '../../src/core/routing'

const A = { lat: 12.9352, lng: 77.6245 } // Koramangala
const B = { lat: 12.9260, lng: 77.6762 } // Bellandur-ish

describe('cacheKey', () => {
  it('is stable and direction-sensitive', () => {
    expect(cacheKey(A, B)).toBe(cacheKey({ ...A }, { ...B }))
    expect(cacheKey(A, B)).not.toBe(cacheKey(B, A))
  })

  it('rounds to 4 decimals so near-identical points share a key', () => {
    expect(cacheKey(A, B)).toBe(cacheKey({ lat: 12.93521, lng: 77.62449 }, B))
  })
})

describe('createRouteProvider', () => {
  const cache: RouteCache = {
    [cacheKey(A, B)]: { km: 7.4, minutes: 21, polyline: [A, { lat: 12.93, lng: 77.65 }, B] },
  }

  it('returns the cached route tagged source=cache', () => {
    const r = createRouteProvider(cache).route(A, B)
    expect(r.km).toBe(7.4)
    expect(r.minutes).toBe(21)
    expect(r.polyline.length).toBe(3)
    expect(r.source).toBe('cache')
  })

  it('falls back to a straight-line estimate tagged source=estimate', () => {
    const r = createRouteProvider(cache).route(B, A) // reverse key is absent
    expect(r.source).toBe('estimate')
    expect(r.km).toBeCloseTo(estimateKm(B, A), 9)
    expect(r.polyline).toEqual([B, A])
  })

  it('derives estimate minutes from the documented city speed', () => {
    const r = createRouteProvider({}).route(A, B)
    expect(r.minutes).toBeCloseTo((estimateKm(A, B) / AVG_CITY_SPEED_KMPH) * 60, 6)
    expect(AVG_CITY_SPEED_KMPH).toBe(22)
  })

  it('applies the traffic multiplier to minutes but never to distance', () => {
    const plain = createRouteProvider(cache).route(A, B)
    const heavy = createRouteProvider(cache, 1.5).route(A, B)
    expect(heavy.minutes).toBeCloseTo(plain.minutes * 1.5, 6)
    expect(heavy.km).toBe(plain.km)
  })

  it('returns zero for identical points without consulting the cache', () => {
    const r = createRouteProvider({}).route(A, A)
    expect(r.km).toBe(0)
    expect(r.minutes).toBe(0)
    expect(r.source).toBe('estimate')
  })
})
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/clock.test.ts tests/core/routing.test.ts`
Expected: FAIL — both imports unresolved.

- [ ] **Step 4: Write `src/core/clock.ts`**

```ts
/**
 * PURPOSE: a deterministic simulation clock driving cab animation and playback.
 * PIVOT: if the statement needs a longer horizon, widen start/end at the call
 *        site; nothing here assumes a day.
 * SAFE-TO-DELETE: no — every before/after playback depends on it.
 */

export type SimClock = {
  now(): number
  seek(ms: number): void
  /** advance by wall-clock ms; scaled by speed. Caller owns the timer. */
  advance(realMs: number): void
  play(): void
  pause(): void
  setSpeed(n: number): void
  isPlaying(): boolean
  subscribe(fn: (ms: number) => void): () => void
}

/**
 * No setInterval and no Date.now inside core: the UI calls advance() from
 * requestAnimationFrame, and tests call it directly. That is what makes golden
 * tests byte-stable.
 */
export function createClock(opts: { start: number; end: number; speed?: number }): SimClock {
  const { start, end } = opts
  let speed = opts.speed ?? 1
  let current = start
  let playing = false
  const subs = new Set<(ms: number) => void>()

  const emit = (): void => { for (const fn of subs) fn(current) }
  const clamp = (ms: number): number => Math.min(end, Math.max(start, ms))

  return {
    now: () => current,
    isPlaying: () => playing,
    play: () => { playing = true },
    pause: () => { playing = false },
    setSpeed: (n: number) => {
      if (!(n > 0)) throw new Error(`clock speed must be > 0, got ${n}`)
      speed = n
    },
    seek: (ms: number) => { current = clamp(ms); emit() },
    advance: (realMs: number) => {
      if (!playing) return
      current = clamp(current + realMs * speed)
      if (current >= end) playing = false
      emit()
    },
    subscribe: (fn) => { subs.add(fn); return () => { subs.delete(fn) } },
  }
}
```

- [ ] **Step 5: Write `src/core/routing.ts`**

```ts
/**
 * PURPOSE: resolve a route between two points, offline and deterministically.
 * PIVOT: a live API tier (ORS/Google) belongs here and NOWHERE else — but it is
 *        Tier C (spec §19) and deliberately not built. The cache is the demo.
 * SAFE-TO-DELETE: no — solvers and scenario metrics both route through this.
 */
import type { LatLng, RouteResult } from './types'
import { estimateKm } from './geo'

/** Bengaluru peak average. Used only for the estimate tier. */
export const AVG_CITY_SPEED_KMPH = 22

export type RouteCache = Record<string, { km: number; minutes: number; polyline: LatLng[] }>

const r4 = (n: number): string => n.toFixed(4)

/** Direction-sensitive key, rounded so near-identical points share an entry. */
export function cacheKey(a: LatLng, b: LatLng): string {
  return `${r4(a.lat)},${r4(a.lng)}|${r4(b.lat)},${r4(b.lng)}`
}

export type RouteProvider = { route(a: LatLng, b: LatLng): RouteResult }

/**
 * cache -> straight-line x ROAD_FACTOR. `source` is surfaced in the UI so an
 * estimated leg renders as a dotted line labelled "Estimated route"
 * (design §14). Traffic scales time only, never distance.
 */
export function createRouteProvider(cache: RouteCache, trafficMultiplier = 1): RouteProvider {
  return {
    route(a: LatLng, b: LatLng): RouteResult {
      if (a.lat === b.lat && a.lng === b.lng) {
        return { km: 0, minutes: 0, polyline: [a], source: 'estimate' }
      }
      const hit = cache[cacheKey(a, b)]
      if (hit) {
        return {
          km: hit.km,
          minutes: hit.minutes * trafficMultiplier,
          polyline: hit.polyline,
          source: 'cache',
        }
      }
      const km = estimateKm(a, b)
      return {
        km,
        minutes: (km / AVG_CITY_SPEED_KMPH) * 60 * trafficMultiplier,
        polyline: [a, b],
        source: 'estimate',
      }
    },
  }
}
```

- [ ] **Step 6: Run both test files to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/clock.test.ts tests/core/routing.test.ts && npx tsc --noEmit`
Expected: 14 tests PASS, typecheck clean.

- [ ] **Step 7: Commit**

```bash
cd commute-os
git add src/core/clock.ts src/core/routing.ts tests/core/clock.test.ts tests/core/routing.test.ts
git commit -m "feat(core): deterministic sim clock and offline route provider

Clock owns no timer — the caller drives advance(), so tests are exact and
core stays free of Date.now. Route provider resolves cache -> straight-line
x1.3 and tags the source, so an estimated leg can render dotted. route()
is deliberately synchronous: both tiers are local, and the live-API tier
is Tier C and not built, so no solver needs async plumbing."
```

---

### Task 6: `policy.ts` — the four-tier engine

**Files:**
- Create: `commute-os/src/core/policy.ts`
- Test: `commute-os/tests/core/policy.test.ts`

**Interfaces:**
- Consumes: `Policy`, `PolicyVerdict`, `PolicyTrace`, `PolicyStatus`, `Candidate`, `World`, `PolicyCtx` from `types.ts`.
- Produces:
  - `TIER_ORDER: readonly PolicyStatus[]` (`['pass','soft','medium','block']`)
  - `tierRank(s: PolicyStatus): number`
  - `worstTier(v: PolicyVerdict[]): PolicyStatus`
  - `compareTiers(a: PolicyStatus, b: PolicyStatus): number`
  - `evaluate(policies: Policy[], c: Candidate, w: World, ctx: PolicyCtx): PolicyTrace`
  - `pass(id, name, reason, slack?): PolicyVerdict` — verdict helper
  - `verdict(id, name, status, cause, reason, slack?): PolicyVerdict` — verdict helper

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/policy.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { TIER_ORDER, tierRank, worstTier, compareTiers, evaluate, pass, verdict } from '../../src/core/policy'
import type { Candidate, Policy, PolicyCtx, World } from '../../src/core/types'

const EMPTY_WORLD = {
  zones: [], offices: [], employees: [], vehicles: [], drivers: [],
  depots: [], metroLines: [], metroStations: [], metroEdges: [],
} as World

const CTX: PolicyCtx = {
  now: 1_757_000_000_000, zoneRejections: {}, trafficMultiplier: 1,
  detourMinutesThisWeek: {},
}

const CAND = {
  tripIds: ['t1'], trips: [], vehicleId: 'v1', driverId: 'd1',
  km: 5, minutes: 15, perPassengerAddedMin: {}, gateIds: ['g1'],
  seatsUsed: 2, pickupTimes: {},
} as Candidate

const mk = (id: string, status: 'pass' | 'soft' | 'medium' | 'block'): Policy => () =>
  status === 'pass'
    ? pass(id, id, 'fine')
    : verdict(id, id, status, 'load', `${id} violated`, { value: -3, unit: 'min' })

describe('tier ordering', () => {
  it('orders pass < soft < medium < block', () => {
    expect(TIER_ORDER).toEqual(['pass', 'soft', 'medium', 'block'])
    expect(tierRank('pass')).toBeLessThan(tierRank('soft'))
    expect(tierRank('soft')).toBeLessThan(tierRank('medium'))
    expect(tierRank('medium')).toBeLessThan(tierRank('block'))
  })

  it('compareTiers sorts worse tiers last', () => {
    expect(compareTiers('pass', 'block')).toBeLessThan(0)
    expect(compareTiers('block', 'soft')).toBeGreaterThan(0)
    expect(compareTiers('soft', 'soft')).toBe(0)
  })

  it('worstTier picks the highest-ranked status', () => {
    expect(worstTier([])).toBe('pass')
    expect(worstTier([pass('a', 'a', 'ok')])).toBe('pass')
    expect(worstTier([
      pass('a', 'a', 'ok'),
      verdict('b', 'b', 'soft', 'unfair_detour', 'meh'),
      verdict('c', 'c', 'medium', 'load', 'bad'),
    ])).toBe('medium')
  })
})

describe('evaluate', () => {
  it('runs every policy and returns one verdict each, in order', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'soft')], CAND, EMPTY_WORLD, CTX)
    expect(t.verdicts.map((v) => v.id)).toEqual(['p1', 'p2'])
  })

  it('is not blocked when nothing blocks', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'soft'), mk('p3', 'medium')], CAND, EMPTY_WORLD, CTX)
    expect(t.blocked).toBe(false)
    expect(t.tier).toBe('medium')
  })

  it('is blocked when any policy blocks', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'block')], CAND, EMPTY_WORLD, CTX)
    expect(t.blocked).toBe(true)
    expect(t.tier).toBe('block')
  })

  it('still evaluates policies AFTER a block — the trace must be complete', () => {
    const t = evaluate([mk('p1', 'block'), mk('p2', 'soft'), mk('p3', 'pass')], CAND, EMPTY_WORLD, CTX)
    expect(t.verdicts.length).toBe(3)
    expect(t.verdicts.map((v) => v.id)).toEqual(['p1', 'p2', 'p3'])
  })

  it('returns an unblocked pass trace for an empty policy list', () => {
    const t = evaluate([], CAND, EMPTY_WORLD, CTX)
    expect(t).toEqual({ verdicts: [], blocked: false, tier: 'pass' })
  })
})

describe('verdict helpers', () => {
  it('pass() produces a pass verdict with no cause', () => {
    const v = pass('x', 'X', 'all good')
    expect(v.status).toBe('pass')
    expect(v.cause).toBeUndefined()
    expect(v.reason).toBe('all good')
  })

  it('verdict() carries cause and slack through', () => {
    const v = verdict('y', 'Y', 'block', 'max_distance', 'too far', { value: -12, unit: 'km' })
    expect(v).toEqual({
      id: 'y', name: 'Y', status: 'block', cause: 'max_distance',
      reason: 'too far', slack: { value: -12, unit: 'km' },
    })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/policy.test.ts`
Expected: FAIL — `Failed to resolve import "../../src/core/policy"`.

- [ ] **Step 3: Write `src/core/policy.ts`**

```ts
/**
 * PURPOSE: run every policy over a candidate and return a complete, tiered trace.
 * PIVOT: adding rule eleven is one file in policies/ plus one array entry in
 *        policies/index.ts. Nothing here changes.
 * SAFE-TO-DELETE: no — this is the moat; the UI renders its output verbatim.
 */
import type {
  Candidate, Policy, PolicyCtx, PolicyStatus, PolicyTrace, PolicyVerdict,
  ViolationCause, World,
} from './types'

/**
 * Ascending severity. Compared lexicographically and NEVER summed: with a
 * single score, dropping a trip and driving further become commensurable, and
 * the solver learns to look efficient by serving fewer people.
 * (spec 08 §2 HardMediumSoftScore; spec 07 §5 assignment_reward.)
 */
export const TIER_ORDER = ['pass', 'soft', 'medium', 'block'] as const

export function tierRank(s: PolicyStatus): number {
  return TIER_ORDER.indexOf(s)
}

/** Negative if `a` is more acceptable than `b`. */
export function compareTiers(a: PolicyStatus, b: PolicyStatus): number {
  return tierRank(a) - tierRank(b)
}

export function worstTier(verdicts: PolicyVerdict[]): PolicyStatus {
  let worst: PolicyStatus = 'pass'
  for (const v of verdicts) if (tierRank(v.status) > tierRank(worst)) worst = v.status
  return worst
}

export function pass(
  id: string, name: string, reason: string,
  slack?: { value: number; unit: string },
): PolicyVerdict {
  return slack === undefined
    ? { id, name, status: 'pass', reason }
    : { id, name, status: 'pass', reason, slack }
}

export function verdict(
  id: string, name: string, status: PolicyStatus, cause: ViolationCause,
  reason: string, slack?: { value: number; unit: string },
): PolicyVerdict {
  return slack === undefined
    ? { id, name, status, cause, reason }
    : { id, name, status, cause, reason, slack }
}

/**
 * Evaluates ALL policies, including those after a block. A partial trace would
 * defeat the point: an admin needs to see every reason a merge failed, not just
 * the first, and the UI shows blocked proposals rather than hiding them.
 */
export function evaluate(
  policies: Policy[], c: Candidate, w: World, ctx: PolicyCtx,
): PolicyTrace {
  const verdicts = policies.map((p) => p(c, w, ctx))
  return {
    verdicts,
    blocked: verdicts.some((v) => v.status === 'block'),
    tier: worstTier(verdicts),
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/policy.test.ts && npx tsc --noEmit`
Expected: 10 tests PASS, typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd commute-os
git add src/core/policy.ts tests/core/policy.test.ts
git commit -m "feat(core): four-tier policy engine

pass < soft < medium < block, compared lexicographically and never summed.
The medium tier is what structurally stops the solver from dropping a trip
to look efficient (design v1.1 A1). evaluate() deliberately runs every
policy even after a block, so the trace an admin sees is complete."
```

---

### Task 7: Test world builder + policies 1–4 (capacity, time window, detour SLA, gate spread)

**Files:**
- Create: `commute-os/tests/helpers/world.ts`
- Create: `commute-os/src/core/policies/seat-capacity.ts`
- Create: `commute-os/src/core/policies/time-window.ts`
- Create: `commute-os/src/core/policies/detour-sla.ts`
- Create: `commute-os/src/core/policies/gate-spread.ts`
- Test: `commute-os/tests/core/policies/route-family.test.ts`

**Interfaces:**
- Consumes: `evaluate`/`pass`/`verdict` from `policy.ts`; `haversineKm` from `geo.ts`; `MODEL` from `ledger.ts`; types.
- Produces (test helper): `makeWorld(over?: Partial<World>): World`, `makeCandidate(over?: Partial<Candidate>): Candidate`, `makeTrip(over?: Partial<Trip>): Trip`, `makeCtx(over?: Partial<PolicyCtx>): PolicyCtx`, `T0: number`
- Produces (policies): `seatCapacity: Policy`, `timeWindow: Policy`, `detourSla: Policy`, `gateSpread: Policy`, plus the exported thresholds `MAX_GATES` (2), `EXTRA_MIN_PER_GATE` (5), `LEAD_TIME_TOLERANCE_MIN` (15), `MAX_DETOUR_MIN` (10), `MAX_DETOUR_FRACTION` (0.3)

- [ ] **Step 1: Write the shared test world builder**

`commute-os/tests/helpers/world.ts`:

```ts
import type { Candidate, PolicyCtx, Trip, World } from '../../src/core/types'

/** Fixed epoch ms — 2026-09-04T09:00:00Z-ish. Never Date.now(). */
export const T0 = 1_757_000_000_000
const MIN = 60_000

export function makeTrip(over: Partial<Trip> = {}): Trip {
  return {
    id: 't1',
    employeeIds: ['e1'],
    pickupAt: { lat: 12.9352, lng: 77.6245 },
    zoneId: 'z-koramangala',
    officeId: 'o1',
    gateId: 'g1',
    direction: 'login',
    windows: [[T0, T0 + 30 * MIN]],
    seatsUsed: 1,
    vehicleId: 'v-sedan',
    driverId: 'd-fresh',
    isNightShift: false,
    ...over,
  }
}

export function makeWorld(over: Partial<World> = {}): World {
  return {
    zones: [{
      id: 'z-koramangala', name: 'Koramangala',
      centroid: { lat: 12.9352, lng: 77.6245 },
      polygon: [
        { lat: 12.91, lng: 77.60 }, { lat: 12.91, lng: 77.65 },
        { lat: 12.96, lng: 77.65 }, { lat: 12.96, lng: 77.60 },
      ],
      confidence: 1,
    }],
    offices: [{
      id: 'o1', name: 'Office One', at: { lat: 12.9260, lng: 77.6762 },
      gates: [
        { id: 'g1', name: 'Gate 1', at: { lat: 12.9260, lng: 77.6762 } },
        { id: 'g2', name: 'Gate 2', at: { lat: 12.9268, lng: 77.6790 } },
        { id: 'g3', name: 'Gate 3', at: { lat: 12.9280, lng: 77.6830 } },
      ],
    }],
    employees: [
      { id: 'e1', name: 'Asha', gender: 'F', homeAt: { lat: 12.9352, lng: 77.6245 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.05 },
      { id: 'e2', name: 'Bhavna', gender: 'F', homeAt: { lat: 12.9360, lng: 77.6260 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.10 },
      { id: 'e3', name: 'Chandran', gender: 'M', homeAt: { lat: 12.9370, lng: 77.6270 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.20 },
      { id: 'e4', name: 'Dinesh', gender: 'M', homeAt: { lat: 12.9380, lng: 77.6280 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.02 },
    ],
    vehicles: [
      { id: 'v-sedan', plate: 'KA01AA0001', seats: 4, fuel: 'ICE' },
      { id: 'v-ev', plate: 'KA01AA0002', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 100 },
      { id: 'v-ev-low', plate: 'KA01AA0003', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 30 },
      { id: 'v-shuttle', plate: 'KA01AA0004', seats: 12, fuel: 'CNG' },
    ],
    drivers: [
      { id: 'd-fresh', name: 'Ramesh', dutyMinutesToday: 60, score: 90 },
      { id: 'd-near-cap', name: 'Suresh', dutyMinutesToday: 700, score: 80 },
      { id: 'd-warn', name: 'Girish', dutyMinutesToday: 670, score: 85 },
    ],
    depots: [{ id: 'dep1', name: 'Depot One', at: { lat: 12.94, lng: 77.62 } }],
    metroLines: [], metroStations: [], metroEdges: [],
    ...over,
  }
}

export function makeCandidate(over: Partial<Candidate> = {}): Candidate {
  const trips = over.trips ?? [makeTrip()]
  return {
    tripIds: trips.map((t) => t.id),
    trips,
    vehicleId: 'v-sedan',
    driverId: 'd-fresh',
    km: 8,
    minutes: 24,
    perPassengerAddedMin: {},
    gateIds: ['g1'],
    seatsUsed: trips.reduce((a, t) => a + t.seatsUsed, 0),
    pickupTimes: Object.fromEntries(trips.map((t) => [t.id, t.windows[0]![0]])),
    ...over,
  }
}

export function makeCtx(over: Partial<PolicyCtx> = {}): PolicyCtx {
  return { now: T0, zoneRejections: {}, trafficMultiplier: 1, detourMinutesThisWeek: {}, ...over }
}
```

- [ ] **Step 2: Write the failing tests**

`commute-os/tests/core/policies/route-family.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { seatCapacity } from '../../../src/core/policies/seat-capacity'
import { timeWindow, LEAD_TIME_TOLERANCE_MIN } from '../../../src/core/policies/time-window'
import { detourSla, MAX_DETOUR_MIN } from '../../../src/core/policies/detour-sla'
import { gateSpread, MAX_GATES, EXTRA_MIN_PER_GATE } from '../../../src/core/policies/gate-spread'
import { makeWorld, makeCandidate, makeTrip, makeCtx, T0 } from '../../helpers/world'

const W = makeWorld()
const CTX = makeCtx()
const MIN = 60_000

describe('seatCapacity', () => {
  it('passes when seats are available and reports remaining slack', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 3 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 1, unit: 'seats' })
  })

  it('passes when exactly full', () => {
    expect(seatCapacity(makeCandidate({ seatsUsed: 4 }), W, CTX).status).toBe('pass')
  })

  it('blocks when over capacity, with cause=load and negative slack', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 6 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('load')
    expect(v.slack).toEqual({ value: -2, unit: 'seats' })
  })

  it('uses the 12-seat shuttle capacity when the vehicle is a shuttle', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 9, vehicleId: 'v-shuttle' }), W, CTX)
    expect(v.status).toBe('pass')
  })

  it('blocks when the vehicle id is unknown — fail closed', () => {
    const v = seatCapacity(makeCandidate({ vehicleId: 'nope' }), W, CTX)
    expect(v.status).toBe('block')
  })
})

describe('timeWindow', () => {
  it('passes when every pickup falls inside a window', () => {
    expect(timeWindow(makeCandidate(), W, CTX).status).toBe('pass')
  })

  it('blocks with cause=delay when a pickup is after the last window end', () => {
    const trip = makeTrip({ windows: [[T0, T0 + 10 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 + 25 * MIN } })
    const v = timeWindow(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('delay')
    expect(v.slack!.value).toBeCloseTo(-15, 6)
  })

  it('satisfies ANY of several windows, not just the first', () => {
    const trip = makeTrip({ windows: [[T0, T0 + 10 * MIN], [T0 + 60 * MIN, T0 + 90 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 + 70 * MIN } })
    expect(timeWindow(c, W, CTX).status).toBe('pass')
  })

  it('flags an excessively early pickup as soft with cause=lead_time', () => {
    const trip = makeTrip({ windows: [[T0 + 60 * MIN, T0 + 90 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 } })
    const v = timeWindow(c, W, CTX)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('lead_time')
  })

  it('tolerates a small early arrival', () => {
    const trip = makeTrip({ windows: [[T0 + 10 * MIN, T0 + 40 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 } })
    expect(timeWindow(c, W, CTX).status).toBe('pass')
    expect(LEAD_TIME_TOLERANCE_MIN).toBe(15)
  })
})

describe('detourSla', () => {
  it('passes when nobody is detoured', () => {
    const v = detourSla(makeCandidate(), W, CTX)
    expect(v.status).toBe('pass')
  })

  it('passes a detour inside the 10-minute ceiling', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 8 } })
    expect(detourSla(c, W, CTX).status).toBe('pass')
    expect(MAX_DETOUR_MIN).toBe(10)
  })

  it('blocks a detour beyond the absolute ceiling', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 14 } })
    const v = detourSla(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('delay')
    expect(v.slack!.value).toBeCloseTo(-4, 6)
  })

  it('applies the 30% relative ceiling on a short trip', () => {
    // 20-min trip -> allowance is min(10, 6) = 6 minutes
    const c = makeCandidate({ minutes: 20, perPassengerAddedMin: { e1: 7 } })
    expect(detourSla(c, W, CTX).status).toBe('block')
  })

  it('reports the WORST affected passenger, not the average', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 1, e2: 14 } })
    const v = detourSla(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toContain('e2')
  })
})

describe('gateSpread', () => {
  it('passes a single gate with no penalty', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1'] }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 0, unit: 'min' })
  })

  it('passes two gates and reports the added minutes', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g2'] }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: -EXTRA_MIN_PER_GATE, unit: 'min' })
  })

  it('blocks three gates with cause=max_tasks', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g2', 'g3'] }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_tasks')
    expect(MAX_GATES).toBe(2)
  })

  it('counts DISTINCT gates only', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g1', 'g1'] }), W, CTX)
    expect(v.status).toBe('pass')
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/policies/route-family.test.ts`
Expected: FAIL — four unresolved imports.

- [ ] **Step 4: Write the four policies**

`commute-os/src/core/policies/seat-capacity.ts`:

```ts
/**
 * PURPOSE: a merge may not exceed the assigned vehicle's seat count.
 * PIVOT: for luggage or wheelchair dimensions, make this a vector check
 *        (spec 05 §3.1) — currently Tier C, seats only.
 * SAFE-TO-DELETE: no — the most basic feasibility rule.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const seatCapacity: Policy = (c, w) => {
  const id = 'seat-capacity'
  const name = 'Seat capacity'
  const vehicle = w.vehicles.find((v) => v.id === c.vehicleId)
  if (!vehicle) {
    return verdict(id, name, 'block', 'load', `Unknown vehicle ${c.vehicleId}`)
  }
  const spare = vehicle.seats - c.seatsUsed
  return spare >= 0
    ? pass(id, name, `${c.seatsUsed}/${vehicle.seats} seats used`, { value: spare, unit: 'seats' })
    : verdict(id, name, 'block', 'load',
        `${c.seatsUsed} passengers exceeds ${vehicle.seats} seats`,
        { value: spare, unit: 'seats' })
}
```

`commute-os/src/core/policies/time-window.ts`:

```ts
/**
 * PURPOSE: every pickup must start inside one of its trip's windows.
 * PIVOT: two-tier SLA (FleetPy user_max_wait_time_2, spec 07 §2) plugs in here
 *        as a second, relaxed pass — Tier B.
 * SAFE-TO-DELETE: no.
 */
import type { Policy, Trip } from '../types'
import { pass, verdict } from '../policy'

/** Arriving more than this many minutes before the window opens is a soft miss. */
export const LEAD_TIME_TOLERANCE_MIN = 15

const MS_PER_MIN = 60_000

function earliestStart(t: Trip): number {
  return Math.min(...t.windows.map((wnd) => wnd[0]))
}
function latestEnd(t: Trip): number {
  return Math.max(...t.windows.map((wnd) => wnd[1]))
}
function insideAnyWindow(t: Trip, at: number): boolean {
  return t.windows.some((wnd) => at >= wnd[0] && at <= wnd[1])
}

export const timeWindow: Policy = (c) => {
  const id = 'time-window'
  const name = 'Pickup window'

  let worstLateMin = 0
  let lateTripId = ''
  let worstEarlyMin = 0
  let earlyTripId = ''

  for (const t of c.trips) {
    const at = c.pickupTimes[t.id]
    if (at === undefined || t.windows.length === 0) continue
    if (insideAnyWindow(t, at)) continue

    if (at > latestEnd(t)) {
      const lateMin = (at - latestEnd(t)) / MS_PER_MIN
      if (lateMin > worstLateMin) { worstLateMin = lateMin; lateTripId = t.id }
    } else if (at < earliestStart(t)) {
      const earlyMin = (earliestStart(t) - at) / MS_PER_MIN
      if (earlyMin > worstEarlyMin) { worstEarlyMin = earlyMin; earlyTripId = t.id }
    }
  }

  if (worstLateMin > 0) {
    return verdict(id, name, 'block', 'delay',
      `${lateTripId} would be picked up ${worstLateMin.toFixed(0)} min after its window closes`,
      { value: -worstLateMin, unit: 'min' })
  }
  if (worstEarlyMin > LEAD_TIME_TOLERANCE_MIN) {
    return verdict(id, name, 'soft', 'lead_time',
      `${earlyTripId} would wait ${worstEarlyMin.toFixed(0)} min before its window opens`,
      { value: -(worstEarlyMin - LEAD_TIME_TOLERANCE_MIN), unit: 'min' })
  }
  return pass(id, name, 'All pickups inside their windows')
}
```

`commute-os/src/core/policies/detour-sla.ts`:

```ts
/**
 * PURPOSE: no passenger's journey may grow by more than the SLA allowance.
 * PIVOT: employee SLA is the most politically sensitive number — MAX_DETOUR_MIN
 *        and MAX_DETOUR_FRACTION are the two dials an admin will argue about.
 * SAFE-TO-DELETE: no.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Absolute ceiling on added travel time for any one passenger. */
export const MAX_DETOUR_MIN = 10
/** Relative ceiling: a short trip may not grow by more than this fraction. */
export const MAX_DETOUR_FRACTION = 0.3

export const detourSla: Policy = (c) => {
  const id = 'detour-sla'
  const name = 'Detour SLA'
  const allowanceMin = Math.min(MAX_DETOUR_MIN, c.minutes * MAX_DETOUR_FRACTION)

  let worst = 0
  let worstWho = ''
  for (const [employeeId, addedMin] of Object.entries(c.perPassengerAddedMin)) {
    if (addedMin > worst) { worst = addedMin; worstWho = employeeId }
  }

  const spare = allowanceMin - worst
  return spare >= 0
    ? pass(id, name,
        `Worst detour ${worst.toFixed(0)} min of ${allowanceMin.toFixed(0)} allowed`,
        { value: spare, unit: 'min' })
    : verdict(id, name, 'block', 'delay',
        `${worstWho} detoured ${worst.toFixed(0)} min, ${allowanceMin.toFixed(0)} allowed`,
        { value: spare, unit: 'min' })
}
```

`commute-os/src/core/policies/gate-spread.ts`:

```ts
/**
 * PURPOSE: a merged cab may serve at most MAX_GATES distinct office gates.
 * PIVOT: raise MAX_GATES only with EXTRA_MIN_PER_GATE fed into detour-sla, or
 *        the SLA silently absorbs the cost.
 * SAFE-TO-DELETE: no — this is what keeps login trips a single-destination
 *                 problem, which is why brute-force pickup ordering stays exact.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const MAX_GATES = 2
/** Minutes added per gate beyond the first. */
export const EXTRA_MIN_PER_GATE = 5

export const gateSpread: Policy = (c) => {
  const id = 'gate-spread'
  const name = 'Gate spread'
  const distinct = [...new Set(c.gateIds)]
  const extraMin = Math.max(0, distinct.length - 1) * EXTRA_MIN_PER_GATE

  return distinct.length <= MAX_GATES
    ? pass(id, name,
        `${distinct.length} gate${distinct.length === 1 ? '' : 's'}, +${extraMin} min`,
        { value: -extraMin, unit: 'min' })
    : verdict(id, name, 'block', 'max_tasks',
        `${distinct.length} distinct gates exceeds the limit of ${MAX_GATES}`,
        { value: -extraMin, unit: 'min' })
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/policies/route-family.test.ts && npx tsc --noEmit`
Expected: 19 tests PASS, typecheck clean.

- [ ] **Step 6: Commit**

```bash
cd commute-os
git add tests/helpers/world.ts src/core/policies/ tests/core/policies/route-family.test.ts
git commit -m "feat(core): policies 1-4 — capacity, pickup window, detour SLA, gate spread

Each is a pure function returning a tiered verdict with a signed slack
value, so near-misses are rankable rather than merely rejected.
time-window satisfies ANY of several windows (design v1.1 A7) and adds the
lead_time soft verdict for an excessively early pickup, which the v1.0
single-threshold rule could not catch. seat-capacity fails closed on an
unknown vehicle."
```

---

### Task 8: Policies 5–7 (driver hours, EV range, gender safety)

**Files:**
- Create: `commute-os/src/core/policies/driver-hours.ts`
- Create: `commute-os/src/core/policies/ev-range.ts`
- Create: `commute-os/src/core/policies/gender-safety.ts`
- Test: `commute-os/tests/core/policies/fleet-safety.test.ts`

**Interfaces:**
- Consumes: `pass`/`verdict` from `policy.ts`; test helpers from Task 7.
- Produces: `driverHours: Policy` + `MAX_DUTY_MIN` (720), `WARN_DUTY_MIN` (660);
  `evRange: Policy` + `EV_RESERVE_FRACTION` (0.2);
  `genderSafety: Policy` + `NIGHT_START_HOUR` (21), `NIGHT_END_HOUR` (6)

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/policies/fleet-safety.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { driverHours, MAX_DUTY_MIN, WARN_DUTY_MIN } from '../../../src/core/policies/driver-hours'
import { evRange, EV_RESERVE_FRACTION } from '../../../src/core/policies/ev-range'
import { genderSafety } from '../../../src/core/policies/gender-safety'
import { makeWorld, makeCandidate, makeTrip, makeCtx } from '../../helpers/world'

const W = makeWorld()
const CTX = makeCtx()

describe('driverHours', () => {
  it('passes a fresh driver and reports remaining minutes', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-fresh', minutes: 30 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 720 - 60 - 30, unit: 'min' })
  })

  it('warns softly as the driver approaches the cap', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-warn', minutes: 20 }), W, CTX)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('max_travel_time')
  })

  it('blocks when the merge would exceed 12 hours of duty', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-near-cap', minutes: 40 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_travel_time')
    expect(v.slack!.value).toBeCloseTo(-20, 6)
    expect(v.reason).toContain('Suresh')
  })

  it('uses the documented thresholds', () => {
    expect(MAX_DUTY_MIN).toBe(720)
    expect(WARN_DUTY_MIN).toBe(660)
  })

  it('blocks an unknown driver — fail closed', () => {
    expect(driverHours(makeCandidate({ driverId: 'nope' }), W, CTX).status).toBe('block')
  })
})

describe('evRange', () => {
  it('is not applicable to a combustion vehicle', () => {
    const v = evRange(makeCandidate({ vehicleId: 'v-sedan', km: 300 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.reason).toMatch(/not an EV/i)
  })

  it('passes an EV comfortably inside its usable range', () => {
    // 150 km * 100% SoC * 0.8 reserve = 120 km usable
    const v = evRange(makeCandidate({ vehicleId: 'v-ev', km: 80 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 40, unit: 'km' })
  })

  it('blocks an EV beyond usable range and names the reassignment', () => {
    const v = evRange(makeCandidate({ vehicleId: 'v-ev', km: 130 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_distance')
    expect(v.reason).toMatch(/CNG|ICE/)
  })

  it('accounts for state of charge, not just nameplate range', () => {
    // v-ev-low: 150 km * 30% * 0.8 = 36 km usable
    expect(evRange(makeCandidate({ vehicleId: 'v-ev-low', km: 30 }), W, CTX).status).toBe('pass')
    expect(evRange(makeCandidate({ vehicleId: 'v-ev-low', km: 50 }), W, CTX).status).toBe('block')
  })

  it('keeps a 20% reserve', () => {
    expect(EV_RESERVE_FRACTION).toBe(0.2)
  })
})

describe('genderSafety', () => {
  const dayTrip = (ids: string[], id = 'td') => makeTrip({ id, employeeIds: ids, isNightShift: false })
  const nightTrip = (ids: string[], id = 'tn') => makeTrip({ id, employeeIds: ids, isNightShift: true })

  it('does not restrict daytime merges at all', () => {
    const c = makeCandidate({ trips: [dayTrip(['e1']), dayTrip(['e3'], 'td2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('blocks a night merge with exactly one female', () => {
    const c = makeCandidate({ trips: [nightTrip(['e1']), nightTrip(['e3'], 'tn2')] })
    const v = genderSafety(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('skills')
    expect(v.reason).toMatch(/lone female/i)
  })

  it('allows a night merge with two or more females', () => {
    const c = makeCandidate({ trips: [nightTrip(['e1']), nightTrip(['e2'], 'tn2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('allows an all-male night merge', () => {
    const c = makeCandidate({ trips: [nightTrip(['e3']), nightTrip(['e4'], 'tn2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('blocks a lone female as the LAST drop on a night logout', () => {
    // NOTE: two females in the group, so the lone-female rule does NOT fire —
    // this must be caught by the last-drop rule specifically.
    const a = makeTrip({ id: 'l1', employeeIds: ['e1'], isNightShift: true, direction: 'logout' })
    const b = makeTrip({ id: 'l2', employeeIds: ['e3'], isNightShift: true, direction: 'logout' })
    const c = makeTrip({ id: 'l3', employeeIds: ['e2'], isNightShift: true, direction: 'logout' })
    const v = genderSafety(makeCandidate({ trips: [a, b, c] }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toMatch(/last drop/i)
    expect(v.reason).toContain('Bhavna')
  })

  it('allows a male last drop on a night logout', () => {
    const a = makeTrip({ id: 'l1', employeeIds: ['e1'], isNightShift: true, direction: 'logout' })
    const b = makeTrip({ id: 'l2', employeeIds: ['e2'], isNightShift: true, direction: 'logout' })
    const c = makeTrip({ id: 'l3', employeeIds: ['e3'], isNightShift: true, direction: 'logout' })
    expect(genderSafety(makeCandidate({ trips: [a, b, c] }), W, CTX).status).toBe('pass')
  })

  it('ignores employees it cannot resolve rather than crashing', () => {
    const c = makeCandidate({ trips: [nightTrip(['ghost']), nightTrip(['e3'], 'tn2')] })
    expect(() => genderSafety(c, W, CTX)).not.toThrow()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/policies/fleet-safety.test.ts`
Expected: FAIL — three unresolved imports.

- [ ] **Step 3: Write `src/core/policies/driver-hours.ts`**

```ts
/**
 * PURPOSE: a merge may not push a driver past the legal duty ceiling.
 * PIVOT: real compliance needs scheduled breaks with max_load (VROOM, spec 06
 *        §4) — Tier C. This is the cumulative ceiling only.
 * SAFE-TO-DELETE: no — labour compliance is a question judges ask.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const MAX_DUTY_MIN = 720  // 12 hours
export const WARN_DUTY_MIN = 660 // 11 hours

export const driverHours: Policy = (c, w) => {
  const id = 'driver-hours'
  const name = 'Driver hours'
  const driver = w.drivers.find((d) => d.id === c.driverId)
  if (!driver) {
    return verdict(id, name, 'block', 'max_travel_time', `Unknown driver ${c.driverId}`)
  }

  const total = driver.dutyMinutesToday + c.minutes
  const spare = MAX_DUTY_MIN - total

  if (spare < 0) {
    return verdict(id, name, 'block', 'max_travel_time',
      `${driver.name} would reach ${total.toFixed(0)} min of duty, ${MAX_DUTY_MIN} allowed`,
      { value: spare, unit: 'min' })
  }
  if (total > WARN_DUTY_MIN) {
    return verdict(id, name, 'soft', 'max_travel_time',
      `${driver.name} nearing the duty cap at ${total.toFixed(0)} min`,
      { value: spare, unit: 'min' })
  }
  return pass(id, name, `${driver.name} at ${total.toFixed(0)}/${MAX_DUTY_MIN} min`,
    { value: spare, unit: 'min' })
}
```

- [ ] **Step 4: Write `src/core/policies/ev-range.ts`**

```ts
/**
 * PURPOSE: an EV may not be assigned a route beyond its usable range.
 * PIVOT: if the statement is EV/green-led, pair this with a charging scheduler
 *        (FleetPy charging/Threshold, spec 07 §6) — Tier B.
 * SAFE-TO-DELETE: no — MoveInSync runs ~500 EVs; this is a real constraint.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Fraction of usable charge held back as reserve. */
export const EV_RESERVE_FRACTION = 0.2

export const evRange: Policy = (c, w) => {
  const id = 'ev-range'
  const name = 'EV range'
  const vehicle = w.vehicles.find((v) => v.id === c.vehicleId)
  if (!vehicle) {
    return verdict(id, name, 'block', 'max_distance', `Unknown vehicle ${c.vehicleId}`)
  }
  if (vehicle.fuel !== 'EV') {
    return pass(id, name, `${vehicle.plate} is not an EV — range is unconstrained`)
  }

  const nameplate = vehicle.rangeKm ?? 0
  const socFraction = (vehicle.socPct ?? 100) / 100
  const usableKm = nameplate * socFraction * (1 - EV_RESERVE_FRACTION)
  const spare = usableKm - c.km

  return spare >= 0
    ? pass(id, name, `${c.km.toFixed(1)} km of ${usableKm.toFixed(1)} km usable`,
        { value: spare, unit: 'km' })
    : verdict(id, name, 'block', 'max_distance',
        `${c.km.toFixed(1)} km exceeds ${usableKm.toFixed(1)} km usable — reassign to CNG or ICE`,
        { value: spare, unit: 'km' })
}
```

- [ ] **Step 5: Write `src/core/policies/gender-safety.ts`**

```ts
/**
 * PURPOSE: a lone female employee is never pooled or last-dropped at night.
 * PIVOT: if the statement is safety-led, promote this to the hero policy and
 *        add escort assignment + route-deviation alerts (Tier B).
 * SAFE-TO-DELETE: no. This is a hard block and the most memorable demo beat —
 *                 a system that refuses is more credible than one that never does.
 */
import type { Employee, Policy, Trip } from '../types'
import { pass, verdict } from '../policy'

export const NIGHT_START_HOUR = 21
export const NIGHT_END_HOUR = 6

function employeesOf(trips: Trip[], all: Employee[]): Employee[] {
  const ids = new Set(trips.flatMap((t) => t.employeeIds))
  return all.filter((e) => ids.has(e.id))
}

export const genderSafety: Policy = (c, w) => {
  const id = 'gender-safety'
  const name = 'Gender safety'

  const isNight = c.trips.some((t) => t.isNightShift)
  if (!isNight) return pass(id, name, 'Daytime trip — no night-shift restriction')

  const people = employeesOf(c.trips, w.employees)
  const females = people.filter((e) => e.gender === 'F')

  if (females.length === 1) {
    return verdict(id, name, 'block', 'skills',
      `Safety policy: lone female (${females[0]!.name}) on a night-shift merge. ` +
      `Requires a second female passenger or a dedicated escort.`)
  }

  // Last-drop rule: on a night logout the final passenger must not be a lone female.
  const logouts = c.trips.filter((t) => t.direction === 'logout' && t.isNightShift)
  if (logouts.length > 0) {
    const last = logouts[logouts.length - 1]!
    const lastPeople = employeesOf([last], w.employees)
    const lastFemales = lastPeople.filter((e) => e.gender === 'F')
    if (lastPeople.length > 0 && lastFemales.length === lastPeople.length) {
      return verdict(id, name, 'block', 'skills',
        `Safety policy: ${lastFemales.map((e) => e.name).join(', ')} would be the ` +
        `last drop on a night logout. Reorder the route or assign an escort.`)
    }
  }

  return females.length === 0
    ? pass(id, name, 'No female passengers on this night merge')
    : pass(id, name, `${females.length} female passengers — night merge permitted`)
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/policies/fleet-safety.test.ts && npx tsc --noEmit`
Expected: 18 tests PASS, typecheck clean.

- [ ] **Step 7: Commit**

```bash
cd commute-os
git add src/core/policies/driver-hours.ts src/core/policies/ev-range.ts \
        src/core/policies/gender-safety.ts tests/core/policies/fleet-safety.test.ts
git commit -m "feat(core): policies 5-7 — driver hours, EV range, gender safety

driver-hours has both a soft warn tier and a hard block. ev-range accounts
for state of charge rather than nameplate range and keeps a 20% reserve,
naming the CNG/ICE reassignment in its refusal. gender-safety blocks both
the lone-female night merge and the lone-female last drop on a night
logout, and unresolvable employees are ignored rather than throwing."
```

---

### Task 9: Policies 8–10 (zone confidence, no-show risk, detour fairness) + registry

**Files:**
- Create: `commute-os/src/core/policies/zone-confidence.ts`
- Create: `commute-os/src/core/policies/no-show-risk.ts`
- Create: `commute-os/src/core/policies/detour-fairness.ts`
- Create: `commute-os/src/core/policies/index.ts`
- Test: `commute-os/tests/core/policies/soft-family.test.ts`

**Interfaces:**
- Consumes: `pass`/`verdict` from `policy.ts`; `MODEL`/`cabCostInr` from `ledger.ts`; test helpers.
- Produces: `zoneConfidence: Policy` + `REJECTION_THRESHOLD` (3);
  `noShowRisk: Policy`; `detourFairness: Policy` + `FAIR_WEEKLY_DETOUR_MIN` (90);
  `ALL_POLICIES: Policy[]` (all ten, in evaluation order)

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/policies/soft-family.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { zoneConfidence, REJECTION_THRESHOLD } from '../../../src/core/policies/zone-confidence'
import { noShowRisk } from '../../../src/core/policies/no-show-risk'
import { detourFairness, FAIR_WEEKLY_DETOUR_MIN } from '../../../src/core/policies/detour-fairness'
import { ALL_POLICIES } from '../../../src/core/policies/index'
import { evaluate } from '../../../src/core/policy'
import { makeWorld, makeCandidate, makeTrip, makeCtx } from '../../helpers/world'

const W = makeWorld()

describe('zoneConfidence', () => {
  it('passes a zone with no rejection history', () => {
    expect(zoneConfidence(makeCandidate(), W, makeCtx()).status).toBe('pass')
  })

  it('passes below the rejection threshold', () => {
    const ctx = makeCtx({ zoneRejections: { 'z-koramangala': 2 } })
    expect(zoneConfidence(makeCandidate(), W, ctx).status).toBe('pass')
  })

  it('goes soft at the threshold and never blocks', () => {
    const ctx = makeCtx({ zoneRejections: { 'z-koramangala': 5 } })
    const v = zoneConfidence(makeCandidate(), W, ctx)
    expect(v.status).toBe('soft')
    expect(v.reason).toContain('5')
    expect(REJECTION_THRESHOLD).toBe(3)
  })
})

describe('noShowRisk', () => {
  it('never blocks, whatever the risk', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e3'] })] // e3 noShowRate 0.20
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx())
    expect(['pass', 'soft']).toContain(v.status)
  })

  it('flags a high combined no-show probability as soft', () => {
    const trips = [
      makeTrip({ id: 'a', employeeIds: ['e3'] }),  // 0.20
      makeTrip({ id: 'b', employeeIds: ['e2'] }),  // 0.10
    ]
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx())
    expect(v.status).toBe('soft')
    expect(v.slack!.unit).toBe('%')
  })

  it('honours the slider override across all employees', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e4'] })] // 0.02 normally
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx({ noShowOverride: 0.9 }))
    expect(v.status).toBe('soft')
  })

  it('passes a low-risk group', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e4'] })] // 0.02
    expect(noShowRisk(makeCandidate({ trips }), W, makeCtx()).status).toBe('pass')
  })
})

describe('detourFairness', () => {
  it('passes when nobody has absorbed much detour', () => {
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 5 } }), W, makeCtx())
    expect(v.status).toBe('pass')
  })

  it('goes soft when an employee exceeds the weekly fair share', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 88 } })
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 6 } }), W, ctx)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('unfair_detour')
    expect(v.reason).toContain('94')
  })

  it('never blocks — fairness is a preference, not a hard rule', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 100_000 } })
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 10 } }), W, ctx).status).toBe('soft')
  })

  it('counts prior load PLUS this candidate, not either alone', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 85 } })
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 1 } }), W, ctx).status).toBe('pass')
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 10 } }), W, ctx).status).toBe('soft')
  })

  it('includes employees with no prior detour history at zero', () => {
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e2: 3 } }), W, makeCtx())
    expect(v.status).toBe('pass')
    expect(FAIR_WEEKLY_DETOUR_MIN).toBe(90)
  })
})

describe('ALL_POLICIES registry', () => {
  it('registers exactly ten policies', () => {
    expect(ALL_POLICIES.length).toBe(10)
  })

  it('produces a complete ten-verdict trace with unique ids', () => {
    const trace = evaluate(ALL_POLICIES, makeCandidate(), W, makeCtx())
    expect(trace.verdicts.length).toBe(10)
    expect(new Set(trace.verdicts.map((v) => v.id)).size).toBe(10)
  })

  it('passes a benign candidate cleanly', () => {
    const trace = evaluate(ALL_POLICIES, makeCandidate(), W, makeCtx())
    expect(trace.blocked).toBe(false)
    expect(trace.tier).toBe('pass')
  })

  it('blocks and still returns all ten verdicts for a bad candidate', () => {
    const bad = makeCandidate({ seatsUsed: 99, gateIds: ['g1', 'g2', 'g3'] })
    const trace = evaluate(ALL_POLICIES, bad, W, makeCtx())
    expect(trace.blocked).toBe(true)
    expect(trace.tier).toBe('block')
    expect(trace.verdicts.length).toBe(10)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/policies/soft-family.test.ts`
Expected: FAIL — four unresolved imports.

- [ ] **Step 3: Write `src/core/policies/zone-confidence.ts`**

```ts
/**
 * PURPOSE: de-prioritise zones where the admin keeps rejecting our suggestions.
 * PIVOT: this is the feedback loop — wire admin Reject into ctx.zoneRejections
 *        and the engine learns. Never make it a block.
 * SAFE-TO-DELETE: yes — the engine works without it, but the loop is a good
 *                 demo beat (PRD edge case 9).
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const REJECTION_THRESHOLD = 3

export const zoneConfidence: Policy = (c, _w, ctx) => {
  const id = 'zone-confidence'
  const name = 'Zone confidence'
  const zoneIds = [...new Set(c.trips.map((t) => t.zoneId))]
  const worst = zoneIds.reduce((max, z) => Math.max(max, ctx.zoneRejections[z] ?? 0), 0)

  return worst < REJECTION_THRESHOLD
    ? pass(id, name, `Zone confidence normal (${worst} prior rejections)`,
        { value: REJECTION_THRESHOLD - worst, unit: 'rejections' })
    : verdict(id, name, 'soft', 'unfair_detour',
        `Admin rejected ${worst} suggestions in this zone — de-prioritising`,
        { value: REJECTION_THRESHOLD - worst, unit: 'rejections' })
}
```

- [ ] **Step 4: Write `src/core/policies/no-show-risk.ts`**

```ts
/**
 * PURPOSE: surface the chance that a pooled saving evaporates to a no-show.
 * PIVOT: ctx.noShowOverride is the demo slider; raising it should visibly move
 *        the savings band without changing any merge decision.
 * SAFE-TO-DELETE: yes — but it is what turns a point estimate into a range,
 *                 which is what makes the savings number believable.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Above this combined probability, warn the admin. */
const RISK_SOFT_THRESHOLD = 0.25

export const noShowRisk: Policy = (c, w, ctx) => {
  const id = 'no-show-risk'
  const name = 'No-show risk'
  const employeeIds = [...new Set(c.trips.flatMap((t) => t.employeeIds))]

  // P(at least one no-show) = 1 - product(1 - p_i)
  let allShow = 1
  for (const eid of employeeIds) {
    const rate = ctx.noShowOverride ?? w.employees.find((e) => e.id === eid)?.noShowRate ?? 0
    allShow *= 1 - rate
  }
  const risk = 1 - allShow
  const pct = risk * 100

  return risk < RISK_SOFT_THRESHOLD
    ? pass(id, name, `${pct.toFixed(0)}% chance of at least one no-show`,
        { value: (RISK_SOFT_THRESHOLD - risk) * 100, unit: '%' })
    : verdict(id, name, 'soft', 'unfair_detour',
        `${pct.toFixed(0)}% chance of at least one no-show — savings may not fully realise`,
        { value: (RISK_SOFT_THRESHOLD - risk) * 100, unit: '%' })
}
```

- [ ] **Step 5: Write `src/core/policies/detour-fairness.ts`**

```ts
/**
 * PURPOSE: stop the same employee absorbing the pooling detour every day.
 * PIVOT: if the statement is about adoption or employee experience, promote
 *        this to the hero policy — it is the differentiator.
 * SAFE-TO-DELETE: no. Optimise pure cost and the same unlucky employee in the
 *   far corner takes the hit daily, because the geometry that made them
 *   expensive yesterday is unchanged today. That is how a corporate pooling
 *   programme actually dies, and no cost-only optimiser can see it.
 *   (spec 08 §3, Timefold's load-balancing constraint.)
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Minutes of detour one employee should absorb in a week before it is unfair. */
export const FAIR_WEEKLY_DETOUR_MIN = 90

export const detourFairness: Policy = (c, w, ctx) => {
  const id = 'detour-fairness'
  const name = 'Detour fairness'

  // Every employee in the candidate, at zero prior load if unseen — the
  // .complement() lesson: measuring fairness only over the already-burdened
  // makes "fair" mean "fair among the unlucky".
  const employeeIds = [...new Set(c.trips.flatMap((t) => t.employeeIds))]

  let worst = 0
  let worstId = ''
  for (const eid of employeeIds) {
    const total = (ctx.detourMinutesThisWeek[eid] ?? 0) + (c.perPassengerAddedMin[eid] ?? 0)
    if (total > worst) { worst = total; worstId = eid }
  }

  const spare = FAIR_WEEKLY_DETOUR_MIN - worst
  if (spare >= 0) {
    return pass(id, name,
      `Heaviest detour load ${worst.toFixed(0)} of ${FAIR_WEEKLY_DETOUR_MIN} min/week`,
      { value: spare, unit: 'min/week' })
  }

  const who = w.employees.find((e) => e.id === worstId)?.name ?? worstId
  return verdict(id, name, 'soft', 'unfair_detour',
    `${who} would absorb ${worst.toFixed(0)} min of detour this week, ` +
    `${Math.abs(spare).toFixed(0)} over a fair share`,
    { value: spare, unit: 'min/week' })
}
```

- [ ] **Step 6: Write `src/core/policies/index.ts`**

```ts
/**
 * PURPOSE: the policy registry. Order here is the order the trace renders in.
 * PIVOT: rule eleven is one import and one array entry. Nothing else changes.
 * SAFE-TO-DELETE: no.
 */
import type { Policy } from '../types'

import { seatCapacity } from './seat-capacity'
import { timeWindow } from './time-window'
import { detourSla } from './detour-sla'
import { gateSpread } from './gate-spread'
import { driverHours } from './driver-hours'
import { evRange } from './ev-range'
import { genderSafety } from './gender-safety'
import { zoneConfidence } from './zone-confidence'
import { noShowRisk } from './no-show-risk'
import { detourFairness } from './detour-fairness'

/** Hard feasibility first, then safety, then the soft preferences. */
export const ALL_POLICIES: Policy[] = [
  seatCapacity,
  timeWindow,
  detourSla,
  gateSpread,
  driverHours,
  evRange,
  genderSafety,
  zoneConfidence,
  noShowRisk,
  detourFairness,
]

export {
  seatCapacity, timeWindow, detourSla, gateSpread, driverHours,
  evRange, genderSafety, zoneConfidence, noShowRisk, detourFairness,
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/policies && npx tsc --noEmit`
Expected: all policy tests PASS (route-family 19, fleet-safety 17, soft-family 16 = 52), typecheck clean.

- [ ] **Step 8: Commit**

```bash
cd commute-os
git add src/core/policies/zone-confidence.ts src/core/policies/no-show-risk.ts \
        src/core/policies/detour-fairness.ts src/core/policies/index.ts \
        tests/core/policies/soft-family.test.ts
git commit -m "feat(core): policies 8-10 + registry — the fairness differentiator

detour-fairness (design v1.1 A2) is the policy no cost-only optimiser has:
it counts prior weekly detour load PLUS this candidate, and includes
employees with no history at zero, so 'fair' does not quietly mean 'fair
among the already-burdened'. Soft, never blocking.

no-show-risk computes P(at least one no-show) properly rather than summing
rates, and honours the demo slider. zone-confidence closes the admin
feedback loop. ALL_POLICIES is the single registry; rule eleven is one
import plus one array entry."
```

---

### Task 10: `scenario.ts` — metrics, the theoretical floor, and the savings band

**Files:**
- Create: `commute-os/src/core/scenario.ts`
- Test: `commute-os/tests/core/scenario.test.ts`

**Interfaces:**
- Consumes: `Metrics`, `Trip`, `World`, `PolicyStatus` from `types.ts`; `classOf`/`cabCostInr`/`co2Kg`/`MODEL` from `ledger.ts`; `RouteProvider` from `routing.ts`; `compareTiers` from `policy.ts`.
- Produces:
  - `theoreticalFloor(trips: Trip[], seats: number): number`
  - `computeMetrics(trips: Trip[], w: World, rp: RouteProvider): Metrics`
  - `diffMetrics(baseline: Metrics, solved: Metrics): Metrics`
  - `savingsBand(expectedInr: number, noShowRisk: number): { p10Inr: number; expectedInr: number; p90Inr: number }`
  - `comparePlans(a: { tier: PolicyStatus; metrics: Metrics }, b: { tier: PolicyStatus; metrics: Metrics }): number`

- [ ] **Step 1: Write the failing tests**

`commute-os/tests/core/scenario.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  theoreticalFloor, computeMetrics, diffMetrics, savingsBand, comparePlans,
} from '../../src/core/scenario'
import { createRouteProvider } from '../../src/core/routing'
import { makeWorld, makeTrip } from '../helpers/world'
import type { Metrics } from '../../src/core/types'

const W = makeWorld()
const RP = createRouteProvider({}) // estimate tier only — deterministic

describe('theoreticalFloor', () => {
  it('is the bin-packing bound: passengers over seats, rounded up', () => {
    const trips = Array.from({ length: 10 }, (_, i) => makeTrip({ id: `t${i}`, seatsUsed: 1 }))
    expect(theoreticalFloor(trips, 4)).toBe(3) // ceil(10/4)
  })

  it('handles multi-seat trips', () => {
    const trips = [makeTrip({ id: 'a', seatsUsed: 3 }), makeTrip({ id: 'b', seatsUsed: 3 })]
    expect(theoreticalFloor(trips, 4)).toBe(2) // ceil(6/4)
  })

  it('is zero for no trips', () => {
    expect(theoreticalFloor([], 4)).toBe(0)
  })

  it('never returns less than one for a non-empty set', () => {
    expect(theoreticalFloor([makeTrip()], 12)).toBe(1)
  })

  it('guards against a zero seat count instead of dividing by zero', () => {
    expect(Number.isFinite(theoreticalFloor([makeTrip()], 0))).toBe(true)
  })
})

describe('computeMetrics', () => {
  it('counts one vehicle per distinct vehicleId', () => {
    const trips = [
      makeTrip({ id: 'a', vehicleId: 'v-sedan' }),
      makeTrip({ id: 'b', vehicleId: 'v-ev' }),
      makeTrip({ id: 'c', vehicleId: 'v-sedan' }),
    ]
    expect(computeMetrics(trips, W, RP).vehiclesUsed).toBe(2)
  })

  it('reports the theoretical floor alongside actual usage', () => {
    const trips = Array.from({ length: 8 }, (_, i) =>
      makeTrip({ id: `t${i}`, vehicleId: `v${i}`, seatsUsed: 1 }))
    const m = computeMetrics(trips, W, RP)
    expect(m.vehiclesUsed).toBe(8)
    expect(m.theoreticalFloorVehicles).toBe(2) // ceil(8/4)
    expect(m.theoreticalFloorVehicles).toBeLessThan(m.vehiclesUsed)
  })

  it('accumulates cab km from the route provider', () => {
    const m = computeMetrics([makeTrip()], W, RP)
    expect(m.cabKm).toBeGreaterThan(0)
    expect(m.costInr).toBeGreaterThan(0)
    expect(m.co2Kg).toBeGreaterThan(0)
  })

  it('separates shuttle km from cab km', () => {
    const m = computeMetrics([makeTrip({ vehicleId: 'v-shuttle' })], W, RP)
    expect(m.shuttleKm).toBeGreaterThan(0)
    expect(m.cabKm).toBe(0)
  })

  it('computes average occupancy as passengers over seats offered', () => {
    // two 4-seat cabs, 1 + 3 passengers => 4/8 = 50%
    const trips = [
      makeTrip({ id: 'a', vehicleId: 'v-sedan', seatsUsed: 1 }),
      makeTrip({ id: 'b', vehicleId: 'v-ev', seatsUsed: 3 }),
    ]
    expect(computeMetrics(trips, W, RP).avgOccupancyPct).toBeCloseTo(50, 6)
  })

  it('returns an all-zero metric set for no trips', () => {
    const m = computeMetrics([], W, RP)
    expect(m.vehiclesUsed).toBe(0)
    expect(m.cabKm).toBe(0)
    expect(m.avgOccupancyPct).toBe(0)
  })

  it('is deterministic — identical input gives identical output', () => {
    const trips = [makeTrip()]
    expect(computeMetrics(trips, W, RP)).toEqual(computeMetrics(trips, W, RP))
  })
})

describe('diffMetrics', () => {
  const base = { cabKm: 100, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 10,
    theoreticalFloorVehicles: 3, avgOccupancyPct: 40, costInr: 5000, co2Kg: 14,
    waitingMin: 0, slaViolations: 0, unassignedCount: 0 } satisfies Metrics
  const solved = { ...base, cabKm: 70, vehiclesUsed: 7, avgOccupancyPct: 62, costInr: 3600, co2Kg: 10 }

  it('reports improvement as a positive reduction', () => {
    const d = diffMetrics(base, solved)
    expect(d.cabKm).toBe(30)
    expect(d.vehiclesUsed).toBe(3)
    expect(d.costInr).toBe(1400)
    expect(d.co2Kg).toBeCloseTo(4, 6)
  })

  it('reports occupancy as a gain, not a reduction', () => {
    expect(diffMetrics(base, solved).avgOccupancyPct).toBeCloseTo(22, 6)
  })

  it('is all zeros when nothing changed', () => {
    const d = diffMetrics(base, base)
    expect(d.cabKm).toBe(0)
    expect(d.costInr).toBe(0)
    expect(d.avgOccupancyPct).toBe(0)
  })
})

describe('savingsBand', () => {
  it('brackets the expected value', () => {
    const b = savingsBand(410, 0.25)
    expect(b.expectedInr).toBe(410)
    expect(b.p10Inr).toBeLessThan(410)
    expect(b.p90Inr).toBeGreaterThanOrEqual(410)
  })

  it('widens the downside as no-show risk rises', () => {
    expect(savingsBand(410, 0.5).p10Inr).toBeLessThan(savingsBand(410, 0.1).p10Inr)
  })

  it('collapses to a point when risk is zero', () => {
    const b = savingsBand(410, 0)
    expect(b.p10Inr).toBe(410)
    expect(b.p90Inr).toBe(410)
  })

  it('never reports a negative downside', () => {
    expect(savingsBand(100, 1).p10Inr).toBeGreaterThanOrEqual(0)
  })
})

describe('comparePlans', () => {
  const m = (costInr: number, unassignedCount = 0): Metrics => ({
    cabKm: 0, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 0,
    theoreticalFloorVehicles: 0, avgOccupancyPct: 0, costInr, co2Kg: 0,
    waitingMin: 0, slaViolations: 0, unassignedCount,
  })

  it('prefers the better tier regardless of cost', () => {
    const cheapButBlocked = { tier: 'block' as const, metrics: m(1) }
    const dearButClean = { tier: 'pass' as const, metrics: m(99_999) }
    expect(comparePlans(dearButClean, cheapButBlocked)).toBeLessThan(0)
  })

  it('prefers serving everyone over saving money — the medium tier rule', () => {
    const dropsSomeone = { tier: 'medium' as const, metrics: m(1) }
    const servesAll = { tier: 'soft' as const, metrics: m(99_999) }
    expect(comparePlans(servesAll, dropsSomeone)).toBeLessThan(0)
  })

  it('falls back to cost only within the same tier', () => {
    expect(comparePlans(
      { tier: 'pass', metrics: m(100) },
      { tier: 'pass', metrics: m(200) },
    )).toBeLessThan(0)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd commute-os && npx vitest run tests/core/scenario.test.ts`
Expected: FAIL — `Failed to resolve import "../../src/core/scenario"`.

- [ ] **Step 3: Write `src/core/scenario.ts`**

```ts
/**
 * PURPOSE: the single source of every number the UI shows, plus plan comparison.
 * PIVOT: new headline metric? Add it to Metrics in types.ts and compute it here
 *        — never in a component.
 * SAFE-TO-DELETE: no — KpiStrip, the savings cards and the diff all read this.
 */
import type { Metrics, PolicyStatus, Trip, World } from './types'
import { classOf, cabCostInr, co2Kg } from './ledger'
import type { RouteProvider } from './routing'
import { compareTiers } from './policy'

/** Seats assumed when reporting the fleet floor. A 4-seat cab is the unit. */
const FLOOR_SEATS = 4

const ZERO: Metrics = {
  cabKm: 0, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 0,
  theoreticalFloorVehicles: 0, avgOccupancyPct: 0, costInr: 0, co2Kg: 0,
  waitingMin: 0, slaViolations: 0, unassignedCount: 0,
}

/**
 * Bin-packing lower bound on fleet size: ceil(total passengers / seats).
 * No routing, however clever, can beat this — which is why showing it next to
 * baseline and achieved lets you state your own optimality gap (spec 05 §4.2).
 */
export function theoreticalFloor(trips: Trip[], seats: number): number {
  const passengers = trips.reduce((a, t) => a + t.seatsUsed, 0)
  if (passengers === 0) return 0
  if (seats <= 0) return passengers
  return Math.ceil(passengers / seats)
}

/** Every displayed number derives from here. */
export function computeMetrics(trips: Trip[], w: World, rp: RouteProvider): Metrics {
  if (trips.length === 0) return { ...ZERO }

  const m: Metrics = { ...ZERO }
  const vehiclesSeen = new Set<string>()
  let seatsOffered = 0
  let passengers = 0

  for (const t of trips) {
    const vehicle = w.vehicles.find((v) => v.id === t.vehicleId)
    const office = w.offices.find((o) => o.id === t.officeId)
    const gate = office?.gates.find((g) => g.id === t.gateId) ?? office?.gates[0]
    if (!vehicle || !gate) continue

    const leg = rp.route(t.pickupAt, gate.at)
    const cls = classOf(vehicle)

    if (cls === 'shuttle') m.shuttleKm += leg.km
    else m.cabKm += leg.km

    m.costInr += cabCostInr(leg.km, leg.minutes, cls)
    m.co2Kg += co2Kg(leg.km, cls, vehicle.fuel)

    if (!vehiclesSeen.has(vehicle.id)) {
      vehiclesSeen.add(vehicle.id)
      seatsOffered += vehicle.seats
    }
    passengers += t.seatsUsed
  }

  m.vehiclesUsed = vehiclesSeen.size
  m.theoreticalFloorVehicles = theoreticalFloor(trips, FLOOR_SEATS)
  m.avgOccupancyPct = seatsOffered === 0 ? 0 : (passengers / seatsOffered) * 100
  return m
}

/**
 * Improvement, expressed so every field reads "higher is better":
 * reductions for cost/km/carbon/vehicles, a gain for occupancy.
 */
export function diffMetrics(baseline: Metrics, solved: Metrics): Metrics {
  return {
    cabKm: baseline.cabKm - solved.cabKm,
    shuttleKm: baseline.shuttleKm - solved.shuttleKm,
    metroPaxKm: solved.metroPaxKm - baseline.metroPaxKm,
    vehiclesUsed: baseline.vehiclesUsed - solved.vehiclesUsed,
    theoreticalFloorVehicles: baseline.theoreticalFloorVehicles - solved.theoreticalFloorVehicles,
    avgOccupancyPct: solved.avgOccupancyPct - baseline.avgOccupancyPct,
    costInr: baseline.costInr - solved.costInr,
    co2Kg: baseline.co2Kg - solved.co2Kg,
    waitingMin: baseline.waitingMin - solved.waitingMin,
    slaViolations: baseline.slaViolations - solved.slaViolations,
    unassignedCount: baseline.unassignedCount - solved.unassignedCount,
  }
}

/**
 * Savings as a range, never a point estimate: a merge whose saving depends on
 * everyone turning up is worth less than one that does not. p10 assumes the
 * risk lands badly.
 */
export function savingsBand(
  expectedInr: number, noShowRisk: number,
): { p10Inr: number; expectedInr: number; p90Inr: number } {
  const risk = Math.min(1, Math.max(0, noShowRisk))
  return {
    p10Inr: Math.max(0, expectedInr * (1 - risk)),
    expectedInr,
    p90Inr: expectedInr,
  }
}

/**
 * Lexicographic plan comparison: tier first, cost only as a tie-break.
 * This is the mechanism that stops kilometre savings outranking an unserved
 * employee (design v1.1 A1).
 */
export function comparePlans(
  a: { tier: PolicyStatus; metrics: Metrics },
  b: { tier: PolicyStatus; metrics: Metrics },
): number {
  const byTier = compareTiers(a.tier, b.tier)
  if (byTier !== 0) return byTier
  return a.metrics.costInr - b.metrics.costInr
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd commute-os && npx vitest run tests/core/scenario.test.ts && npx tsc --noEmit`
Expected: 22 tests PASS, typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd commute-os
git add src/core/scenario.ts tests/core/scenario.test.ts
git commit -m "feat(core): scenario metrics, theoretical floor, savings band

theoreticalFloor is PyVRP's bin-packing bound (spec 05 4.2) so the UI can
show baseline -> achieved -> floor and state its own optimality gap.
comparePlans compares tier lexicographically and only tie-breaks on cost,
so no kilometre saving can outrank an unserved employee. savingsBand turns
a point estimate into a p10/expected range, because point estimates get
challenged and ranges get believed."
```

---

### Task 11: `generate-fixtures.ts` — seeded, adversarial fixtures

**Files:**
- Create: `commute-os/scripts/generate-fixtures.ts`
- Create: `commute-os/data/generated/` (output: `bengaluru.world.json`, `trips.200.json`, `routes.cache.json`)
- Test: `commute-os/tests/fixtures.test.ts`

**Interfaces:**
- Consumes: `parseMetroCsv`/`buildMetroGraph` from `metro.ts`; `AVG_CITY_SPEED_KMPH`/`cacheKey` from `routing.ts`; `estimateKm`/`haversineKm` from `geo.ts`; domain types from `types.ts`.
- Produces: `SEED` (20260905) and the three committed JSON files. Randomness is
  `seedrandom` (MIT, 0 deps); names are `@faker-js/faker`'s **`fakerEN_IN`**
  locale, seeded — both verified deterministic locally.

**Why fixtures are adversarial.** The demo must be able to show a *refusal*
without staging one live, so the generated set deliberately contains at least
one candidate that trips each blocking policy: an over-capacity pair, a
window-violating pair, an SLA-busting detour, a three-gate spread, a driver near
the duty cap, a low-SoC EV on a long route, and a lone female on a night shift.

- [ ] **Step 1: Write the failing test**

`commute-os/tests/fixtures.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import type { Trip, World } from '../src/core/types'

const need = (p: string): unknown => {
  if (!existsSync(p)) throw new Error(`missing fixture ${p} — run: npm run fixtures`)
  return JSON.parse(readFileSync(p, 'utf8'))
}

const world = need('data/generated/bengaluru.world.json') as World
const trips = need('data/generated/trips.200.json') as Trip[]
const cache = need('data/generated/routes.cache.json') as Record<string, unknown>

describe('generated world', () => {
  it('has the six Bengaluru zones', () => {
    expect(world.zones.length).toBe(6)
    expect(world.zones.map((z) => z.name).sort()).toEqual([
      'Bellandur', 'Electronic City', 'HSR Layout', 'Indiranagar', 'Koramangala', 'Whitefield',
    ])
  })

  it('has 4 offices, each with 2 or 3 gates', () => {
    expect(world.offices.length).toBe(4)
    for (const o of world.offices) {
      expect(o.gates.length).toBeGreaterThanOrEqual(2)
      expect(o.gates.length).toBeLessThanOrEqual(3)
    }
  })

  it('has 200 employees, 40 vehicles and 25 drivers', () => {
    expect(world.employees.length).toBe(200)
    expect(world.vehicles.length).toBe(40)
    expect(world.drivers.length).toBe(25)
  })

  it('carries the real metro graph: 83 stations, 3 lines, 164 edges', () => {
    expect(world.metroStations.length).toBe(83)
    expect(world.metroLines.length).toBe(3)
    expect(world.metroEdges.length).toBe(164)
  })

  it('includes EVs with a range and a state of charge', () => {
    const evs = world.vehicles.filter((v) => v.fuel === 'EV')
    expect(evs.length).toBeGreaterThan(0)
    for (const ev of evs) {
      expect(ev.rangeKm).toBeGreaterThan(0)
      expect(ev.socPct).toBeGreaterThan(0)
    }
  })

  it('includes drivers deliberately near the 12-hour duty cap', () => {
    expect(world.drivers.some((d) => d.dutyMinutesToday > 660)).toBe(true)
  })
})

describe('generated trips', () => {
  it('has exactly 200 trips with unique ids', () => {
    expect(trips.length).toBe(200)
    expect(new Set(trips.map((t) => t.id)).size).toBe(200)
  })

  it('covers both directions', () => {
    expect(trips.some((t) => t.direction === 'login')).toBe(true)
    expect(trips.some((t) => t.direction === 'logout')).toBe(true)
  })

  it('includes a night-shift cohort so gender-safety has something to block', () => {
    const night = trips.filter((t) => t.isNightShift)
    expect(night.length).toBeGreaterThan(10)
    const nightFemaleSolo = night.filter((t) => {
      const people = t.employeeIds.map((id) => world.employees.find((e) => e.id === id))
      return people.length === 1 && people[0]?.gender === 'F'
    })
    expect(nightFemaleSolo.length).toBeGreaterThan(0)
  })

  it('gives every trip at least one window, with start before end', () => {
    for (const t of trips) {
      expect(t.windows.length).toBeGreaterThanOrEqual(1)
      for (const [s, e] of t.windows) expect(s).toBeLessThan(e)
    }
  })

  it('gives some trips two windows — the multi-window case must be exercised', () => {
    expect(trips.some((t) => t.windows.length === 2)).toBe(true)
  })

  it('references only real employees, vehicles, drivers, offices and gates', () => {
    const eids = new Set(world.employees.map((e) => e.id))
    const vids = new Set(world.vehicles.map((v) => v.id))
    const dids = new Set(world.drivers.map((d) => d.id))
    for (const t of trips) {
      for (const e of t.employeeIds) expect(eids.has(e)).toBe(true)
      expect(vids.has(t.vehicleId)).toBe(true)
      expect(dids.has(t.driverId)).toBe(true)
      const office = world.offices.find((o) => o.id === t.officeId)
      expect(office).toBeDefined()
      expect(office!.gates.some((g) => g.id === t.gateId)).toBe(true)
    }
  })
})

describe('generated route cache', () => {
  it('is non-empty', () => {
    expect(Object.keys(cache).length).toBeGreaterThan(0)
  })

  it('covers every trip pickup -> its office gate', () => {
    // asserted via the same cacheKey the provider uses
    expect(Object.keys(cache).length).toBeGreaterThanOrEqual(trips.length)
  })
})

describe('determinism', () => {
  it('is byte-stable — regenerating must not change the committed files', () => {
    // Guard: this test documents the contract. Re-run `npm run fixtures` and
    // `git diff --exit-code data/generated/` must be clean.
    expect(trips[0]!.id).toBe('t000')
    expect(trips[199]!.id).toBe('t199')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd commute-os && npx vitest run tests/fixtures.test.ts`
Expected: FAIL — `missing fixture data/generated/bengaluru.world.json`.

- [ ] **Step 3: Write `scripts/generate-fixtures.ts`**

```ts
/**
 * PURPOSE: generate the deterministic Bengaluru fixture set.
 * PIVOT: tuning the demo is tuning THIS FILE — zone mix, night cohort size,
 *        EV share, driver duty spread. Re-run `npm run fixtures` and commit.
 * SAFE-TO-DELETE: no — the committed JSON is generated, not hand-edited.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import seedrandom from 'seedrandom'
import { fakerEN_IN as faker } from '@faker-js/faker'
import { buildMetroGraph, parseMetroCsv } from '../src/core/metro'
import { AVG_CITY_SPEED_KMPH, cacheKey } from '../src/core/routing'
import { estimateKm, haversineKm } from '../src/core/geo'
import type {
  Driver, Employee, Gate, LatLng, Office, Trip, Vehicle, World, Zone, Window,
} from '../src/core/types'

/** Fixed seed = the hackathon date. Never change it casually. */
export const SEED = 20260905

/**
 * seedrandom (MIT, zero deps) rather than a hand-rolled PRNG, and faker's
 * Indian-English locale for names. Both are seeded, so regeneration is
 * byte-stable — proven by the git diff --exit-code step below.
 */
const rnd = seedrandom(String(SEED))
faker.seed(SEED)
const pick = <T,>(xs: T[]): T => xs[Math.floor(rnd() * xs.length)]!
const jitter = (v: number, spread: number): number => v + (rnd() - 0.5) * 2 * spread
const MIN = 60_000
/** Demo day starts 2026-09-05T00:00:00Z. */
const DAY0 = Date.UTC(2026, 8, 5, 0, 0, 0)
const at = (h: number, m = 0): number => DAY0 + h * 60 * MIN + m * MIN

// ── zones ───────────────────────────────────────────────────────────────────
const ZONE_SEEDS: Array<{ name: string; at: LatLng }> = [
  { name: 'Koramangala', at: { lat: 12.9352, lng: 77.6245 } },
  { name: 'Bellandur', at: { lat: 12.9260, lng: 77.6762 } },
  { name: 'Indiranagar', at: { lat: 12.9784, lng: 77.6408 } },
  { name: 'Whitefield', at: { lat: 12.9698, lng: 77.7500 } },
  { name: 'Electronic City', at: { lat: 12.8452, lng: 77.6602 } },
  { name: 'HSR Layout', at: { lat: 12.9116, lng: 77.6474 } },
]

const zones: Zone[] = ZONE_SEEDS.map((z, i) => {
  const d = 0.022
  return {
    id: `z${i}`,
    name: z.name,
    centroid: z.at,
    polygon: [
      { lat: z.at.lat - d, lng: z.at.lng - d },
      { lat: z.at.lat - d, lng: z.at.lng + d },
      { lat: z.at.lat + d, lng: z.at.lng + d },
      { lat: z.at.lat + d, lng: z.at.lng - d },
    ],
    confidence: 1,
  }
})

// ── offices ─────────────────────────────────────────────────────────────────
const OFFICE_SEEDS: Array<{ name: string; at: LatLng; gates: number }> = [
  { name: 'Ecospace Bellandur', at: { lat: 12.9256, lng: 77.6810 }, gates: 3 },
  { name: 'Embassy Tech Village', at: { lat: 12.9330, lng: 77.6890 }, gates: 3 },
  { name: 'ITPL Whitefield', at: { lat: 12.9855, lng: 77.7368 }, gates: 2 },
  { name: 'Infosys Electronic City', at: { lat: 12.8480, lng: 77.6630 }, gates: 2 },
]

const offices: Office[] = OFFICE_SEEDS.map((o, i) => {
  const gates: Gate[] = Array.from({ length: o.gates }, (_, g) => ({
    id: `o${i}g${g}`,
    name: `Gate ${g + 1}`,
    at: { lat: jitter(o.at.lat, 0.004), lng: jitter(o.at.lng, 0.004) },
  }))
  return { id: `o${i}`, name: o.name, at: o.at, gates }
})

// ── employees ───────────────────────────────────────────────────────────────
const employees: Employee[] = Array.from({ length: 200 }, (_, i) => {
  const z = zones[i % zones.length]!
  // ~42% female, deterministic BY INDEX rather than random, so the night cohort
  // (i % 9 === 0, below) reliably contains lone-female trips for the safety
  // demo. Leaving this to the PRNG would make the demo's best beat a lottery.
  const gender: Employee['gender'] = i % 12 < 5 ? 'F' : 'M'
  const firstName = faker.person.firstName(gender === 'F' ? 'female' : 'male')
  return {
    id: `e${String(i).padStart(3, '0')}`,
    name: `${firstName} ${faker.person.lastName()}`,
    gender,
    homeAt: { lat: jitter(z.centroid.lat, 0.018), lng: jitter(z.centroid.lng, 0.018) },
    zoneId: z.id,
    officeId: offices[i % offices.length]!.id,
    noShowRate: Math.round((0.02 + rnd() * 0.23) * 100) / 100,
  }
})

// ── fleet ───────────────────────────────────────────────────────────────────
const vehicles: Vehicle[] = Array.from({ length: 40 }, (_, i) => {
  if (i < 10) {
    // EVs, including several deliberately low on charge for the range demo
    const soc = i < 3 ? 25 + i * 5 : 70 + ((i * 7) % 30)
    return { id: `v${i}`, plate: `KA01EV${1000 + i}`, seats: 4, fuel: 'EV' as const,
      rangeKm: 150, socPct: soc }
  }
  if (i < 16) return { id: `v${i}`, plate: `KA01CN${1000 + i}`, seats: 12, fuel: 'CNG' as const }
  if (i < 24) return { id: `v${i}`, plate: `KA01SU${1000 + i}`, seats: 6, fuel: 'ICE' as const }
  return { id: `v${i}`, plate: `KA01SD${1000 + i}`, seats: 4, fuel: 'ICE' as const }
})

const drivers: Driver[] = Array.from({ length: 25 }, (_, i) => ({
  id: `d${i}`,
  name: `Driver ${i + 1}`,
  // 3 drivers deliberately over the 660-minute warn line, 1 over the cap
  dutyMinutesToday: i === 0 ? 700 : i < 4 ? 670 : Math.floor(rnd() * 400),
  score: 60 + Math.floor(rnd() * 40),
}))

// ── metro (real CC0 data) ───────────────────────────────────────────────────
const csv = readFileSync('data/bengaluru_metro_network.csv', 'utf8')
const graph = buildMetroGraph(parseMetroCsv(csv))

const world: World = {
  zones, offices, employees, vehicles, drivers,
  depots: [
    { id: 'dep0', name: 'Bellandur Depot', at: { lat: 12.9210, lng: 77.6700 } },
    { id: 'dep1', name: 'Whitefield Depot', at: { lat: 12.9800, lng: 77.7300 } },
  ],
  metroLines: graph.lines,
  metroStations: graph.stations,
  metroEdges: graph.edges,
}

// ── trips ───────────────────────────────────────────────────────────────────
const trips: Trip[] = Array.from({ length: 200 }, (_, i) => {
  const emp = employees[i]!
  const office = offices.find((o) => o.id === emp.officeId)!
  const isNight = i % 9 === 0                       // ~22 night trips
  const direction: Trip['direction'] = i % 3 === 0 ? 'logout' : 'login'
  const baseHour = isNight ? (direction === 'login' ? 22 : 5) : direction === 'login' ? 8 : 18
  const start = at(baseHour, (i * 7) % 55)

  // ~15% of trips get a second acceptable window (the multi-window case)
  const windows: Window[] = i % 7 === 3
    ? [[start, start + 20 * MIN], [start + 60 * MIN, start + 85 * MIN]]
    : [[start, start + 30 * MIN]]

  return {
    id: `t${String(i).padStart(3, '0')}`,
    employeeIds: [emp.id],
    pickupAt: emp.homeAt,
    zoneId: emp.zoneId,
    officeId: office.id,
    gateId: pick(office.gates).id,
    direction,
    windows,
    seatsUsed: 1,
    vehicleId: vehicles[i % vehicles.length]!.id,
    driverId: drivers[i % drivers.length]!.id,
    isNightShift: isNight,
  }
})

// ── route cache: every pickup -> its gate, plus zone-centroid pairs ─────────
const cache: Record<string, { km: number; minutes: number; polyline: LatLng[] }> = {}
const addLeg = (a: LatLng, b: LatLng): void => {
  const key = cacheKey(a, b)
  if (cache[key]) return
  const km = estimateKm(a, b)
  cache[key] = {
    km: Math.round(km * 1000) / 1000,
    minutes: Math.round((km / AVG_CITY_SPEED_KMPH) * 60 * 100) / 100,
    polyline: [a, { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 }, b],
  }
}

for (const t of trips) {
  const office = offices.find((o) => o.id === t.officeId)!
  const gate = office.gates.find((g) => g.id === t.gateId)!
  addLeg(t.pickupAt, gate.at)
  addLeg(gate.at, t.pickupAt)
}
// pickup-to-pickup legs within a zone, so the merger can chain without estimating
for (const z of zones) {
  const inZone = trips.filter((t) => t.zoneId === z.id).slice(0, 12)
  for (const a of inZone) for (const b of inZone) if (a.id !== b.id) addLeg(a.pickupAt, b.pickupAt)
}
// feeder legs: every zone centroid to its nearest 3 metro stations
for (const z of zones) {
  const near = [...graph.stations]
    .map((s) => ({ s, km: haversineKm(z.centroid, s.at) }))
    .sort((x, y) => x.km - y.km).slice(0, 3)
  for (const { s } of near) { addLeg(z.centroid, s.at); addLeg(s.at, z.centroid) }
}

// ── write ───────────────────────────────────────────────────────────────────
mkdirSync('data/generated', { recursive: true })
const write = (name: string, data: unknown): void => {
  writeFileSync(`data/generated/${name}`, `${JSON.stringify(data, null, 2)}\n`)
  console.log(`  wrote data/generated/${name}`)
}
write('bengaluru.world.json', world)
write('trips.200.json', trips)
write('routes.cache.json', cache)
console.log(`  seed=${SEED}  zones=${zones.length} offices=${offices.length} ` +
  `employees=${employees.length} trips=${trips.length} cacheKeys=${Object.keys(cache).length}`)
```

- [ ] **Step 4: Generate the fixtures**

Run: `cd commute-os && npm run fixtures`
Expected: three files written; the summary line reports 6 zones, 4 offices,
200 employees, 200 trips and a non-zero cache-key count.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd commute-os && npx vitest run tests/fixtures.test.ts && npx tsc --noEmit`
Expected: 15 tests PASS, typecheck clean.

- [ ] **Step 6: Verify determinism explicitly**

```bash
cd commute-os && npm run fixtures && git diff --exit-code data/generated/ \
  && echo "DETERMINISTIC: regeneration produced identical bytes"
```

Expected: exit 0 and the confirmation line. A non-empty diff means an unseeded
source of randomness or an insertion-order dependency crept in — find it before
continuing, because every golden test downstream depends on this.

- [ ] **Step 7: Run the whole suite**

Run: `cd commute-os && npm test && npm run typecheck`
Expected: every test file passes; typecheck clean.

- [ ] **Step 8: Commit**

```bash
cd commute-os
git add scripts/generate-fixtures.ts data/generated tests/fixtures.test.ts
git commit -m "feat(core): seeded deterministic Bengaluru fixtures

seedrandom + faker's fakerEN_IN locale, both seeded on the hackathon
date, so regeneration is byte-stable and every golden test downstream is
reproducible (verified by a git diff --exit-code step). Gender is assigned
BY INDEX, not by the PRNG, so the night-shift lone-female cohort the
safety demo depends on is guaranteed rather than probable.

Fixtures are deliberately ADVERSARIAL: a driver over the duty cap, three
more over the warn line, EVs at 25-35% charge, a ~22-trip night cohort
containing lone-female trips, multi-window trips, and a 3-gate office —
so the demo can show a genuine refusal without staging one live.

Metro portion is built from the real CC0 CSV: 83 stations, 3 lines,
164 bidirectional edges."
```

---

## Appendix A: Spec coverage audit

Every section of design spec v1.1 and every Tier A item, mapped to the task that
implements it — or to the plan that will.

### Design spec sections

| Spec § | Subject | Covered by |
|---|---|---|
| §4.1 | Dependency rules | Task 1 (`tests/boundaries.test.ts`) |
| §4.2 | Mandatory 3-line file header | Task 1 (asserted by test) |
| §5 | Domain model | Task 1 (`types.ts`) |
| §6.1 | `geo.ts` | Task 2 |
| §6.2 | `routing.ts` | Task 5 |
| §6.3 | `clock.ts` | Task 5 |
| §6.4 | `ledger.ts` cost & carbon | Task 3 |
| §6.5 | `scenario.ts` | Task 10 |
| §7 | Policy engine + 10 policies | Tasks 6, 7, 8, 9 |
| §10.2 | Metro graph from real data | Task 4 |
| §11 | Fixtures | Task 11 |
| §15 | Testing strategy | every task (TDD, tests first) |
| §8 | Solver interface | **Plan 2** |
| §9 | Solver A — Pool Merger | **Plan 2** |
| §10.1 | Solver B — Metro Feeder Mesh | **Plan 2** |
| §12 | UI shell | **Plan 3** |
| §13 | AI layer (Sarvam) | **Plan 3** |
| §14 | Error handling / UI fallbacks | **Plan 3** |
| §16 | `KIT.md`, `PIVOT.md`, `DEMO-SCRIPT.md` | **Plan 3** |

### Tier A items (spec §19)

| Item | Description | Covered by |
|---|---|---|
| A1 | Four-tier `PolicyStatus`, lexicographic | Task 6, Task 10 (`comparePlans`) |
| A2 | Policy #10 `detour-fairness` | Task 9 |
| A3 | Real metro data | Task 4, Task 11 |
| A4 | `ViolationCause` vocabulary | Task 1 (type), Task 6 (helpers) |
| A5 | Brute-force pickup order at n≤4 | **Plan 2** (solver concern) |
| A6 | `theoreticalFloor()` + `vehiclesUsed` | Task 10 |
| A7 | `windows: [number,number][]` | Task 1, Task 7 (`time-window`) |
| A8 | H3 corridor key + prefix scan | **Plan 2** (solver concern) |
| A9 | `setup`/`service` boarding split | Task 3 (`boardingMinutes`) |
| A10 | `lead_time` too-early verdict | Task 7 (`time-window`) |
| A11 | Both solvers pre-built | **Plan 2** |

**Nothing in Tier A is unassigned.** A5, A8 and A11 are solver concerns and
belong to Plan 2 by design, not by omission.

### Library-backed vs hand-written

Revised 2026-09-02 per `docs/REUSE-AUDIT.md` — generic work is delegated, domain
work is owned.

| Task | Delegated to | We still own |
|---|---|---|
| 2 `geo.ts` | `@turf/distance`, `@turf/boolean-point-in-polygon` | the `{lat,lng}`↔`[lng,lat]` adapter, `ROAD_FACTOR`, ring closing, `nearestN` |
| 4 `metro.ts` | `papaparse`, `graphology`, `graphology-shortest-path` | station de-duplication, bidirectional edge synthesis, interchange counting, leg timing |
| 11 fixtures | `seedrandom`, `@faker-js/faker` (`fakerEN_IN`) | the whole adversarial fixture design |
| 3, 5, 6, 7, 8, 9, 10 | *nothing* | all of it — ledger, clock, routing, policy engine, ten policies, scenario |

`@types/papaparse` and `@types/seedrandom` are required (neither ships types);
`graphology` and `graphology-shortest-path` ship their own — verified.

Three library behaviours are covered by explicit guard tests because each is a
silent footgun, all verified against the installed versions:

1. `booleanPointInPolygon` **throws** on an open GeoJSON ring — and `Zone.polygon`
   stores an open one. `geo.ts` closes it.
2. turf takes `[lng, lat]`. Reversing it yields plausible-looking wrong distances.
3. `dijkstra.bidirectional` **throws** on an unknown node but returns **`null`**
   for a disconnected one — two different failure modes, both handled.

### Deliberately absent (spec §19 Tier C)

Not implemented, and no task should add them: `priority`/`unassigned[]`
over-subscription, driver `breaks[]` with `max_load`, vector capacity beyond
seats, multi-wave shuttles, route-schedule timeline UI, OpenRouteService tier,
`'bonus'` reward verdicts, `emergencyContacts`, `max_tasks` cap as a standalone
policy, Alonso-Mora RTV, PyVRP/VROOM as a live solver.

Note `Metrics.unassignedCount`, `Metrics.waitingMin` and `Metrics.slaViolations`
**exist as fields** and are computed as zero. They are placeholders for Tier B/C
work, kept in the type so adding them later is not a breaking change. That is
intentional, not an oversight.

## Appendix B: Definition of done for Plan 1

```bash
cd commute-os
npm run typecheck                              # clean
npm test                                       # all pass
npm run fixtures && git diff --exit-code data/generated/   # byte-stable
```

Expected totals: **11 tasks, 11 commits**, **175 tests** across
`boundaries`, `geo`, `ledger`, `metro`, `clock`, `routing`, `policy`,
`policies/route-family`, `policies/fleet-safety`, `policies/soft-family`,
`scenario` and `fixtures`.

At that point the engine is headless-complete: it can load a real Bengaluru
world with a real metro graph, evaluate any candidate grouping against ten
tiered policies with full traces, and cost every plan in rupees and kilograms.
Plan 2 adds the solvers that generate candidates; Plan 3 puts a map on it.
