# 06 — VROOM (Vehicle Routing Open-source Optimization Machine)

**Reuse: 🟢 HIGH — its API schema is the best design template here.**
`github.com/VROOM-Project/vroom` · C++ · 1.8 MB · ⭐1849 · BSD-2-Clause

## 1. What it is

A production VRP solver used behind real routing services, with a clean JSON
HTTP API. Like PyVRP, you won't run it — but `docs/API.md` is a **battle-tested
schema for exactly the problem you're modelling**, and it solves one design
question better than the commute-os spec currently does.

## 2. `skills` — a better mechanism than nine bespoke policies

`docs/API.md:70` (jobs) and `:119` (vehicles):

> `skills` — an array of integers defining mandatory skills

A job carries required skills; a vehicle carries offered skills; a vehicle may
only serve a job whose skills it covers. **One generic mechanism replaces a
family of special-case rules.**

Applied to commute-os, several policies collapse into skill matching:

| Policy | As a skill |
|---|---|
| `gender-safety` | night trip with a lone female requires `FEMALE_SAFE_ESCORT` |
| `ev-range` | a long merged route requires `LONG_RANGE`; EVs don't offer it |
| `gate-spread` | a Gate-5 drop requires `GATE_5_ACCESS` |
| accessibility | requires `WHEELCHAIR` |

**Keep the policy engine** — it produces the *traces* and *slack* values that
are the demo's whole point, and skills alone can't explain themselves. But
implement the pass/fail *check* inside several policies as skill-set matching.
Fewer code paths, and adding rule ten becomes adding an enum member.

## 3. `breaks` — the driver-hours policy, done properly

`docs/API.md:122` — vehicles have a `breaks` array, each with its own time
windows and duration.

The commute-os `driver-hours` policy is a single 12-hour cap. Real compliance is
stricter: a driver needs a mandated break *within* the shift. Modelling breaks
as scheduled obligations rather than one cumulative ceiling is both more correct
and a stronger answer if a judge pushes on labour compliance.

Cheap upgrade: add `breakTaken: boolean` and `breakDueBy: number` to `Driver`,
and have `driver-hours` warn when a merge pushes the break past its window.

## 4. `priority` — what to drop when you can't serve everything

`docs/API.md:71` — `priority`, integer 0–100.

VROOM assumes over-subscription is normal: when not everything fits, priority
decides what gets dropped. The commute-os design has no such concept — it
assumes every trip is served.

Worth adding, because it makes an honest demo moment: *"at 07:45 peak we're 12
cabs short; here's who we serve first and why."* Admitting a constraint and
handling it deliberately reads as more credible than implying infinite supply.

Map `priority` from shift criticality — night-shift and airport-run employees
outrank a flexible 10 am login.

## 5. The rest of the schema, worth copying wholesale

From `docs/API.md`:

- **`shipment`** (`:76`) — a paired pickup+delivery that must ride the same
  vehicle. Exactly an employee trip. Cleaner than commute-os's separate
  `pickupAt` / `officeId` fields.
- **`time_windows`** — an *array* per job, not one window. Real employees have
  "07:00–07:30 or 08:15–08:45", not one interval.
- **`costs`** per vehicle — `fixed` + `per_hour` + `per_km`, mirroring
  `ledger.MODEL`. Confirms that cost model belongs on the vehicle type.
- `docs/example_*.json` + `*_sol.json` — request/response pairs. Model
  `/api/solve`'s response shape on these; they've had years of iteration.

## 6. What to ignore

The entire C++ implementation, CMake build, OSRM/Valhalla wiring. Read
`docs/API.md` and the example JSON. That's the deliverable.

## 7. Verdict

**Read `docs/API.md` end to end — it's the highest value-per-minute document in
this whole reference set.** Then make three changes: express suitability checks
as skill matching, allow an array of time windows per trip, and add `priority`
so over-subscription is handled openly. Roughly an hour, and it makes your data
model look like something that has met production.
