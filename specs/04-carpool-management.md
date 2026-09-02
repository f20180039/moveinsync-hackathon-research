# 04 — Carpool_Management_System

**Reuse: 🔴 LOW — the PRD's claim about this repo is wrong.**
`github.com/parthkvv/Carpool_Management_System` · React 17 · 385 files · **53 MB** ·
last commit 2022-10-03

## 1. Claim vs reality

PRD says: *"Real-time tracking + optimal allocation logic."*

Verified by grep across all of `src/`:

```
haversine · distance · matching · allocat · optimal · directions · DistanceMatrix
  → 0 matches
socket → 14 matches (CometChat SDK internals)
```

**There is no distance calculation, no matching, and no allocation logic in this
repository.** It is a ride *listing and chat* app: post a ride, browse rides,
message the driver. "Real-time" refers to chat, not tracking. Neither claimed
feature exists.

## 2. What it actually contains

```
src/components/{home,chat,ride-list,ride-detail,request-ride,
                register,login,address-picker,common}
src/cometchat-pro-react-ui-kit/     <- ~45 MB of vendored third-party UI kit
src/services/
```

Deps: `leaflet`, `leaflet-routing-machine`, `leaflet-geosearch`, `firebase`,
`@cometchat-pro/chat`, `emoji-mart`, `twemoji`.

Most of the 53 MB and 385 files are the **vendored CometChat UI kit** — not the
authors' code and irrelevant to you.

## 3. The one thing worth a look

`leaflet-routing-machine` in `src/components/address-picker` and `ride-detail`:
a **keyless, free** map + routing stack (Leaflet + OSRM demo server) as an
alternative to Google Directions.

The commute-os design already chooses MapLibre + OSM raster tiles for the same
reason — no key, no billing, no quota. If MapLibre gives trouble, Leaflet +
`leaflet-routing-machine` is a proven fallback, and this repo shows the wiring.
That is the entire extractable value: **one dependency choice, already made.**

Caveat: React 17, `react-scripts`, 2022 vintage. Don't copy component code into
a Next 14 app — patterns and lifecycle assumptions won't transfer cleanly.

## 4. Verdict

**Skim the two Leaflet components for 10 minutes, then close it.** Do not budget
hours here. If disk space matters, this is the one to delete — 53 MB for one
dependency insight.

Also a general lesson: the PRD described this as containing "optimal allocation
logic" and it contains none. Verify reference repos before planning around them
— which is what this survey did, and it changed the plan for two of the five.
