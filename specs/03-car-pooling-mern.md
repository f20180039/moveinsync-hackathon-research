# 03 — Car-Pooling-System (MERN)

**Reuse: 🟡 LOW-MEDIUM — context is worth more than the code.**
`github.com/LohithMarneni/Car-Pooling-System` · MERN · 63 files ·
last commit 2025-04-16 · *reportedly a MoveInSync recruitment assignment*

## 1. What it actually is

A conventional MERN CRUD app: Express + Mongoose + JWT auth, Vite/React/Tailwind
frontend. Users post rides, others request them, driver accepts.

The PRD claims "Auth + Ride matching + Google Maps API planned". Accurate if you
read **"planned"** literally:

> **The entire matching algorithm is commented out.**
> `backend/controllers/rideRequestController.js:30-100` — ~70 lines of haversine
> maths, a match-scoring table, and a `searchRides` implementation, all behind
> `//`. Never shipped. What ships is string-equality on `pickupLocation`.

Worth knowing before you budget any time here.

## 2. What's genuinely useful

### 2.1 The match-percentage table (`rideRequestController.js:37-42`)

Left as a comment. It's a good **UX** idea even though the code died:

| Pickup distance | Drop distance | Match | Meaning |
|---|---|---|---|
| < 2 km | < 2 km | **100%** | Very close at both ends |
| < 2 km | < 5 km | **75%** | One end very close, other reasonable |
| < 5 km | < 2 km | **75%** | Same, swapped |
| < 10 km | < 10 km | **50%** | Same general area |
| > 10 km | > 10 km | **0%** | Excluded |

Why it's worth stealing: **banded confidence beats a raw number**. An admin
reads "92% match" as false precision; "Strong match" / "Fair match" is
actionable. Feed this into `ui/SuggestionFeed.tsx` as the proposal confidence
badge, and into `core/policies/zone-confidence.ts` for de-prioritisation.

### 2.2 `preferences.femaleOnly` (`backend/model/rideSchema.js:13-17`)

```js
preferences: {
  smoking:   { type: Boolean, default: false },
  pets:      { type: Boolean, default: false },
  music:     { type: Boolean, default: false },
  femaleOnly:{ type: Boolean, default: false },
}
```

A precedent for modelling safety as a **first-class trip attribute** rather than
an afterthought — which is what `core/policies/gender-safety.ts` does, more
strictly (it derives from shift time + group composition rather than trusting a
self-set flag).

### 2.3 Haversine (`rideRequestController.js:61-75`)

Commented out but **correct**, with the formula documented in comments above it.
Cheapest possible source for `core/geo.ts:haversineKm`. Port and unit-test it.

## 3. Why the context matters more than the code

If this really is a MoveInSync recruitment assignment, it tells you what they
consider a *baseline* competent submission: auth, CRUD, request/accept flow —
and **matching left as a stretch goal the candidate didn't reach.**

That's your calibration. The thing this candidate ran out of time to do is
precisely the thing `commute-os` pre-builds. Arriving with a working
Clarke-Wright solver and a nine-rule policy engine puts you well past the bar
this repo represents.

It also confirms the gap is real: pooling *logic* is where people run out of
runway, not UI. Which is exactly why the design's cut line (§18) sits after the
solvers and before the UI.

## 4. What to ignore

JWT/bcrypt/cookie auth, CORS config, `logEvents` middleware, Mongoose models,
the React frontend (no map integration at all — `frontend` deps are just
`axios`, `react`, `react-router-dom`). No tests.

## 5. Verdict

Lift the haversine function and the match-banding table — call it 20 minutes.
Then treat the repo as **calibration data** rather than source material: it
shows you where a competent candidate stalls, and that spot is the one you've
pre-solved.
