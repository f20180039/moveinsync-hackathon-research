# 04 — Bengaluru-Metro-Network-Dataset · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/Vinayak-Chinchakhandi/Bengaluru-Metro-Network-Dataset` |
| **Reuse** | 🟢🟢 **HIGHEST** — use this data directly. Do it first. |
| **Contents** | 4 CSVs, 140 KB · 85 rows / 83 unique stations |
| **Licence** | **CC0** per README (GitHub detects no licence file — attribute explicitly) |
| **Activity** | updated 2026-03-20 · ⭐0 · single contributor |
| **Local** | `reference/bengaluru-metro-dataset/` |

The commute-os design spec flags at §17 assumption #1 that metro station
coordinates were **hand-approximated and need verification**. This dataset
retires that assumption and delivers three things the design was guessing at.

---

## 1. Files

| File | Rows | Use |
|---|---|---|
| `bengaluru_metro_network.csv` | 85 | **the one you want** — graph + geometry |
| `bengaluru_metro_stations.csv` | 83 | name → code → line lookup only |
| `data_dictionary.csv` | 10 | column documentation |
| `README.md` | — | CC0 declaration, column descriptions |

### Schema — `bengaluru_metro_network.csv`

```
station_code, station_name, line, sequence, is_interchange,
next_station_code, latitude, longitude, distance_to_next_km, line_color
```

Per `data_dictionary.csv`:

| Column | Meaning |
|---|---|
| `station_code` | unique short code (e.g. `WHTM`, `KGWA`) |
| `station_name` | display name |
| `line` | `Purple Line` \| `Green Line` \| `Yellow Line` |
| `sequence` | order along that line (1-based) |
| `is_interchange` | `1` = interchange, `0` = not |
| `next_station_code` | next station along the line; **NULL at terminals** |
| `latitude` / `longitude` | WGS84, ~15 decimal places |
| `distance_to_next_km` | **real** distance to the next station |
| `line_color` | hex, for map rendering |

Sample row:

```
WHTM,Whitefield (Kadugodi),Purple Line,1,0,UWVL,
12.995699152518254,77.75773036744444,1.04,#7E22CE
```

---

## 2. Verified statistics

Computed directly from the CSV:

| Line | Stations | End-to-end | Colour |
|---|---|---|---|
| Purple | 37 | **40.5 km** | `#7E22CE` |
| Green | 32 | **31.7 km** | `#16A34A` |
| Yellow | 16 | **17.7 km** | `#CA8A04` |
| **Total rows** | **85** | | |
| **Unique station codes** | **83** | | |

- `distance_to_next_km`: n=85, min 0.0, **max 2.03**, **mean 1.06 km**
- Bounding box: lat `12.8196 … 13.0573`, lng `77.4611 … 77.7577`
- `sequence` is contiguous `1..N` on all three lines — **verified, no gaps**

### 2.1 Coordinate spot-checks

Sampled against known locations — all correct:

| Station | Dataset | Sanity |
|---|---|---|
| Mahatma Gandhi Road | 12.97566, 77.60676 | ✅ |
| Nadaprabhu Kempegowda (Majestic) | 12.97559, 77.57313 | ✅ |
| Whitefield (Kadugodi) | 12.99570, 77.75773 | ✅ |
| Central Silk Board | 12.91631, 77.62041 | ✅ |
| Electronic City | 12.85654, 77.66328 | ✅ |

Good enough for a synthetic demo, and far better than hand-typed guesses.

---

## 3. Three data-quality gotchas — read before parsing

### 3.1 The graph is **directed**, one way only

Exactly **three** rows have `next_station_code = NULL`: `Challaghatta` (Purple
seq 37), `Silk Institute` (Green seq 32), `Delta Electronics Bommasandra`
(Yellow seq 16) — one terminal per line.

So the edge list encodes **one direction per line only**. A naive graph build
lets you travel Whitefield → Challaghatta but not back.

**You must synthesise the reverse edges:**

```ts
// scripts/generate-fixtures.ts
for (const r of rows) {
  if (!r.next_station_code) continue
  addEdge(r.station_code, r.next_station_code, r.distance_to_next_km)
  addEdge(r.next_station_code, r.station_code, r.distance_to_next_km)  // ← required
}
```

This matters directly: login trips ride inbound, logout trips ride outbound. Miss
the reverse edges and Metro Feeder Mesh silently returns no logout routes.

### 3.2 The 85-vs-83 discrepancy is the interchanges

Two codes appear twice — once per line:

| Code | Station | Purple/Green row | Green/Yellow row |
|---|---|---|---|
| `KGWA` | Nadaprabhu Kempegowda (Majestic) | Purple seq 23 → `SRCS` · 12.975590, 77.573129 | Green seq 17 → `CKPE` · 12.975663, 77.572662 |
| `RVR` | Rashtreeya Vidyalaya Road | Green seq 24 → `BSNK` · 12.921682, 77.580345 | Yellow seq 1 → `RAGI` · 12.921580, 77.580304 |

**The duplicate rows carry slightly different coordinates** — Majestic's two
rows are ~50 m apart, plausibly the two platform levels. So de-duplication needs
a rule:

```ts
// de-dupe on station_code, keep first, but retain BOTH line memberships
const stations = new Map<string, MetroStation>()
for (const r of rows) {
  const s = stations.get(r.station_code)
  if (s) { s.lineIds.push(r.line); continue }        // second row: add the line only
  stations.set(r.station_code, { ...parse(r), lineIds: [r.line] })
}
```

Fail to do this and Majestic and RV Road are double-counted as separate stations
— which breaks interchange routing precisely at the two points where it matters.

### 3.3 `distance_to_next_km = 0.0` is a terminal sentinel, not a bug

The three zero values are exactly the three terminals. Treat `0` with a NULL
`next_station_code` as "no onward edge" — don't let it become a zero-cost edge
into nowhere.

---

## 4. What this replaces in the commute-os design

| Design assumption | Now sourced from data |
|---|---|
| Hand-typed station coords (§17 #1) | `latitude` / `longitude`, spot-checked |
| **"2.2 min per stop" estimate (§10.1)** | **`distance_to_next_km` — real distances** |
| Hand-guessed interchanges (§10.2) | `is_interchange` — **confirmed exactly 2** |
| Line colours for the map (§12) | `line_color` hex |
| Metro graph adjacency | `next_station_code` (plus reverse edges, §3.1) |

**The design's guesses were right and are now verified.** It predicted the two
interchanges as Majestic (Purple↔Green) and RV Road (Green↔Yellow). Both
confirmed; there are no others.

### Replace the estimated travel time

Design §10.1 uses `metroMin = stops × 2.2 + interchangePenalty`. With real
distances:

```ts
// core/metro.ts
// PURPOSE: metro leg time from real inter-station distances.
// PIVOT: AVG_METRO_SPEED_KMPH and DWELL are the only estimates left.
const AVG_METRO_SPEED_KMPH = 32      // BMRCL scheduled avg incl. dwell
const DWELL_MIN_PER_STOP   = 0.35    // ~20 s
const INTERCHANGE_MIN      = 5

export function metroLegMinutes(path: MetroStation[]): number {
  const km = path.slice(0, -1).reduce((a, s, i) => a + edgeKm(s, path[i + 1]), 0)
  const interchanges = countLineChanges(path)
  return (km / AVG_METRO_SPEED_KMPH) * 60
       + path.length * DWELL_MIN_PER_STOP
       + interchanges * INTERCHANGE_MIN
}
```

Given mean inter-station distance of 1.06 km, the old 2.2 min/stop implied
~29 km/h all-in — so the original guess wasn't far off. But *"we use BMRCL's
published inter-station distances"* is a much better answer than *"we assumed
2.2 minutes"*, and it costs nothing to be right.

---

## 5. The pitch gift — read the Yellow Line

16 stations, `sequence` order from RV Road:

```
 1 Rashtreeya Vidyalaya Road      9 Singasandra
 2 Ragigudda                     10 Hosa Road
 3 Jayadeva Hospital             11 Beratena Agrahara
 4 BTM Layout                    12 Electronic City
 5 Central Silk Board            13 Infosys Foundation Konappana Agrahara
 6 Bommanahalli                  14 Huskur Road
 7 Hongasandra                   15 Biocon Hebbagodi
 8 Kudlu Gate                    16 Delta Electronics Bommasandra
```

**Four of sixteen stations are named after employers** — Infosys, Biocon, Delta
Electronics, plus Electronic City itself. The Yellow Line was built to move
exactly MoveInSync's passengers, over 17.7 km of the densest corporate corridor
in the country.

Put this list on a slide. It's the Metro Feeder Mesh argument, and it isn't a
claim you have to make — the station names make it for you.

Also note `Central Silk Board` (seq 5) is the Green/Yellow-adjacent
interchange-to-be and one of Bengaluru's worst congestion points — useful if the
statement leans on traffic decongestion.

---

## 6. Integration plan

1. Copy both CSVs into `commute-os/data/`.
2. In `scripts/generate-fixtures.ts`, parse `bengaluru_metro_network.csv` and
   emit the metro portion of `bengaluru.world.json`:
   - de-duplicate on `station_code`, accumulating `lineIds` (§3.2)
   - build **bidirectional** edges from `next_station_code` (§3.1)
   - skip terminals for edge creation (§3.3)
   - carry `line_color` through to the map layer
3. Set `FEEDER_RADIUS_KM = 6` / `LAST_MILE_RADIUS_KM = 3` (design §10.1) and
   confirm each office has at least one station in range — with 83 stations
   across a 27 km × 33 km box, Whitefield / Electronic City / Koramangala all
   qualify; verify Bellandur, which is the notorious gap.
4. Attribute the dataset in the README and on the credits slide.

Zero algorithm work. It upgrades Metro Feeder Mesh from plausible-looking mock
to **real network topology with real distances** — which is the difference
between a demo and a claim.

---

## 7. Caveats

- **Community data, not BMRCL official.** 0 stars, one contributor, no CI. The
  five spot-checks in §2.1 pass; I'd check two or three more before demoing.
- **CC0 asserted in the README only** — no `LICENSE` file, so GitHub reports no
  licence. Fine for a hackathon; attribute explicitly rather than silently.
- **Three lines only.** Pink and Blue are under construction and absent —
  correct for a *today* demo, and a good answer if a judge asks about future
  coverage: *"the graph is data-driven, so Pink Line is a CSV row away."*
- **No headways, no fares, no operating hours.** The design's `headwayMin` and
  `metroFarePerTrip` remain assumptions; keep them labelled as such in the
  cost-model panel.
- **`bengaluru_metro_stations.csv` (83 rows) is a strict subset** of the network
  file's information. Ignore it and parse only the network CSV — one source of
  truth avoids the 85/83 confusion entirely.

---

## 8. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | Copy CSVs into `data/`; parse in fixture generator | `scripts/generate-fixtures.ts` | 45 min |
| 2 | **Bidirectional** edges from `next_station_code` | same | 10 min |
| 3 | De-dupe on `station_code`, accumulate `lineIds` | same | 15 min |
| 4 | `metroLegMinutes()` from real distances | `core/metro.ts` | 30 min |
| 5 | Wire `line_color` into `MapCanvas` | `ui/MapCanvas.tsx` | 15 min |
| 6 | Verify feeder radius covers Bellandur | fixture check | 10 min |
| 7 | Yellow Line employer-station list on a slide | pitch | 10 min |
| 8 | Attribute CC0 dataset | README + credits | 5 min |

≈ 2½ hours total, and items 2 and 3 are the ones that silently break Metro
Feeder Mesh if skipped.
