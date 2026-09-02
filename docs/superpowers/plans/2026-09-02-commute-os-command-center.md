# commute-os Command Center — Implementation Plan (Plan 3 of 3)

**Goal:** A working admin command center over Plan 1's engine and Plan 2's
solvers: map, KPI strip, suggestion feed with policy traces, scenario bar,
and the three API routes.

**Deliberately lighter than Plans 1–2.** The UI is the layer the problem
statement will reshape most, so this plan locks the *decisions* (libraries,
layout, component contracts, what each component may import) and leaves visual
detail to the day. Over-specifying screens before the statement is speculation.

**Spec:** design v1.1 §12 (UI shell), §13 (AI), §14 (error handling), §16 (docs).

**New dependencies:** `next@14.x` (pinned for Node 18.19), `react@18`,
`react-dom@18`, `tailwindcss@3`, `maplibre-gl@^6.6.0` (BSD-3-Clause, verified).

## Global Constraints (additions to Plan 1's)
- `src/ui/**` imports only from `src/core/types`, `src/core/ledger`, and
  `src/solvers/solver` (types). **No solver logic in a component.** Extend
  `tests/boundaries.test.ts`.
- Every number on screen comes from `core/scenario.ts`. A component never
  computes a metric.
- **No network call is load-bearing.** Map tiles, Sarvam, and routing all have
  offline fallbacks (§14). The acceptance test is: wifi off, demo still runs.
- Map geometry comes from `routes.cache.json` and `world.metroEdges` — never
  from a live Directions API.

---

### Task 1: Next.js 14 app shell
`app/layout.tsx`, `app/page.tsx`, `app/globals.css`, `tailwind.config.ts`,
`next.config.mjs`, `postcss.config.mjs`; extend `package.json`.

Layout is the PRD's instinct and the design's §12: **map left (≈60%), right
column split** — KPI strip top, suggestion feed middle, scenario bar bottom.
Server component loads the three fixtures once and passes them down; all
interaction is client-side. Done when `npm run build && npm start` serves the
shell with fixtures loaded and no console errors.

### Task 2: `ui/MapCanvas.tsx`
MapLibre GL + OSM raster tiles. Layers: baseline routes grey, solved routes
blue, metro lines in their `line_color` from the CC0 data, `source==='estimate'`
routes **dotted** and labelled "Estimated route" (§14), cab markers with
occupancy badges driven by `core/clock`.

**One data shape to know before you render:** `world.metroEdges` holds **both
directions** of every hop (164 edges for 82 physical segments), because
`buildMetroGraph` synthesises reverse edges — the source CSV is directed and
trains are not. A layer that iterates `metroEdges` will therefore draw every
segment **twice**. Render metro lines from `MetroLine.stationIds` in sequence
order instead, or de-duplicate on an unordered `{from,to}` key.

Two things that matter more than looks:
- **Tile failure must degrade, not blank.** On tile error, render routes over a
  flat background — the routes are the information, the basemap is decoration.
- Occupancy badge updates per step (`1/4 → 2/4 → 4/4`) as the clock advances,
  not a static label (spec 06 §7's `load[]` insight).

### Task 3: `ui/KpiStrip.tsx` + `ui/CostModelPanel.tsx`
KPI strip shows `baseline → solved (Δ)` for occupancy %, cab-km, ₹, kg CO₂ —
and **leads with vehicles**: `174 cabs → 138 → floor 50`. Three numbers, from
`theoreticalFloor` (A6). That trio is the pitch.

`CostModelPanel` is collapsible and renders `ledger.MODEL` beside
`MODEL_BASIS`, so "where does ₹410 come from?" is a click. Includes the EV
honesty line: ~0.10 vs ~0.14 kg/km, a ~30% cut, not zero.

### Task 4: `ui/SuggestionFeed.tsx` + `ui/PolicyTrace.tsx`
Cards per proposal: savings as a **range** (`₹410 expected, ₹180 at p10`), a
banded confidence chip (Strong/Fair/Weak — spec 03 §4.2, not a false-precision
percentage), and Approve / Reject / View on Map / Revert.

`PolicyTrace` renders all ten verdicts with pass/soft/medium/block and remaining
slack. **Blocked proposals are shown, not filtered.** Reject increments
`ctx.zoneRejections`, closing the feedback loop.

Approve applies the proposal to in-memory trip state; Revert un-pools
(edge case 10). Both re-derive metrics from `scenario.ts`.

### Task 5: `ui/ScenarioBar.tsx`
Clock (play/pause/scrub/1×/5×/20×) driving `core/clock.advance()` from
`requestAnimationFrame` — the clock owns no timer, the UI does. Solver selector,
Run button, and the no-show / traffic sliders that move the savings band.

### Task 6: API routes + `ai/sarvam.ts`
`app/api/solve/route.ts` — runs the selected solver, returns the
`SolverResult` shape. Model the response on VROOM's output (spec 06 §7):
`{ code, error?, summary, unassigned[], routes[] }`-shaped, with four numeric
codes rather than HTTP-status soup.

`ai/sarvam.ts` — `explainProposal`, `translate`, `speak`. Each wrapped so a
failure returns a **pre-written deterministic string**, never throws. Env-gated
by `SARVAM_API_KEY`; absent key means fallbacks and the UI still works end to
end. The nudge asks for acceptance (a negotiation, not a notification) and
declining feeds `zoneRejections`.

### Task 7: `KIT.md`, `PIVOT.md`, `docs/DEMO-SCRIPT.md` (§16)
`PIVOT.md` is the one that earns its keep on the day: one row per likely
statement → which solver, which files, what to change, estimated hours.
`DEMO-SCRIPT.md` is the 3-minute beat sheet — problem 20s, baseline board 20s,
run solver 30s, **the refusal 30s**, the headline number 40s, the nudge loop
20s, cost model 20s.

---

## Definition of done for Plan 3
```bash
cd commute-os && npm run typecheck && npm test && npm run build
```
Then the drill that actually matters (`docs/DEPLOYMENTS.md` §5): **turn wifi off
and click through the whole demo script.** If that passes, no deployment can
embarrass you.

## Cut order if time runs short
Per spec §19's override rule: Task 5 sliders → Task 6 Sarvam → Task 2's
animation. Keep map + feed + KPI strip + policy trace; that is the demo.
