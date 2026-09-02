# 03 — Car-Pooling-System (MERN) · Detailed Spec

| | |
|---|---|
| **URL** | `github.com/LohithMarneni/Car-Pooling-System` |
| **Reuse** | 🟡 **LOW** — kept for *calibration*, not for code |
| **Stack** | Express · Mongoose/MongoDB · JWT · React 18 + Vite + Tailwind |
| **Size** | 10 MB · 63 files (23 `.js`, 14 `.jsx`) · last commit 2025-04-16 |
| **Context** | reportedly a **MoveInSync recruitment assignment** |
| **Local** | `reference/Car-Pooling-System/` |

A conventional MERN peer-to-peer carpool app: a driver posts a ride, riders
request to join, the driver approves. Auth, CRUD and the request lifecycle all
work.

**Its value is not the code.** It's evidence of where a competent developer
building this exact product runs out of time — and that spot is precisely what
`commute-os` pre-builds.

---

## 1. Layout

```
backend/
├─ index.js
├─ config/{dbConn,corsOption,allowedOrigins}.js
├─ middleware/{verifyJWT,credentials,errorHandler,logEvents}.js
├─ model/{userSchema,rideSchema,rideRequestSchema}.js
├─ controllers/{auth,user,ride,rideRequest}Controller.js
└─ routes/{auth,user,ride,rideRequest}Routes.js
frontend/                 React 18 + Vite + Tailwind
                          deps: axios, react, react-dom, react-router-dom only
                          — no map library at all
images/  README.md
```

No tests anywhere.

---

## 2. Data model

### `User` (`model/userSchema.js`)

```js
name, email (unique), password, role: enum["rider","driver"], phone,
preferences: { smoking, pets, music, femaleOnly },   // all Boolean, default false
refreshToken,
emergencyContacts: [String],                          // ← note this
createdAt
```

### `Ride` (`model/rideSchema.js`)

```js
driver: ObjectId→User, pickupLocation: String, dropLocation: String,
departureTime: Date, availableSeats: Number,
vehicleDetails: { model, licensePlate },
preferences: { smoking, pets, music, femaleOnly },   // same shape as User
createdAt
```

### `RideRequest` (`model/rideRequestSchema.js`)

```js
ride: ObjectId→Ride, rider: ObjectId→User,
status: enum["pending","approved","rejected"], default "pending",
createdAt
```

### 2.1 The `preferences` duplication is actually a design idea

The **same** preference object appears on both `User` (what a rider wants) and
`Ride` (what a ride offers). That's an informal, un-implemented version of
VROOM's `skills` subset matching (spec 06 §3): rider preferences should be
checked against ride preferences before a match is allowed.

They never wrote the check. But the *shape* is right, and it's the third repo in
this set to model demand and supply as separate entities with matchable
attributes.

### 2.2 `emergencyContacts: [String]` — an unexpected find

An array of emergency contacts on the user, alongside `femaleOnly`. Never used
by any controller. But it's evidence that safety was on the author's mind as a
**data** concern, not just a UI one — and if the problem statement turns out to
be women's safety, `emergencyContacts` plus a route-deviation trigger is a
2-hour feature with real impact.

Add to `Employee` in `core/types.ts`:

```ts
emergencyContacts?: string[]
```

Costs nothing now; unlocks a whole pivot lane later (`PIVOT.md` row 4).

### 2.3 `RideRequest.status` is your `Proposal.status`

`pending | approved | rejected` — the exact state machine as
`Proposal.status: 'suggested' | 'approved' | 'rejected'` in the design (§8).
Third independent confirmation of the demand/supply split (see spec 01 §3,
spec 08 §5).

---

## 3. What actually ships as "matching"

`controllers/rideRequestController.js:8`:

```js
const searchRides = async (req, res) => {
  const { from, to, date } = req.query;
  const dayStart = new Date(date);
  const dayEnd   = new Date(date); dayEnd.setHours(23, 59, 59, 999);

  const rides = await Ride.find({
    pickupLocation: { $regex: from, $options: "i" },
    dropLocation:   { $regex: to,   $options: "i" },
    departureTime:  { $gte: dayStart, $lte: dayEnd },
    availableSeats: { $gt: 0 },
  }).populate("driver", "name email");
  ...
};
```

**A case-insensitive regex substring match on free-text location strings.**

Consequences, all real:

- `"Koramangala"` matches `"Koramangala 5th Block"` — fine by luck
- `"Kormangala"` (one typo) matches nothing
- `"HSR Layout"` 2 km away matches nothing
- `"Bengaluru"` matches every ride in the city
- the date filter is whole-day, so a 06:00 and a 23:00 departure are equivalent

There is no geospatial awareness anywhere in the shipped path. Note also that
the day window is built from `new Date(date)` for the start but only
`setHours(23,59,59,999)` for the end — so `dayStart` inherits whatever time
component the query string carried, which is a latent bug of its own.

---

## 4. What was intended but abandoned

`rideRequestController.js` is **239 lines, 87 of them commented out (36%)**.
Behind the comment markers, at `:44-131`:

- `getCoordinates(address)` — Google Geocoding API call
- `calculateDistance(coord1, coord2)` — a **correct** haversine implementation
- a second `searchRides` that geocodes both endpoints and scores candidates by
  pickup and drop distance

### 4.1 The haversine (`:61-75`)

```js
const calculateDistance = (coord1, coord2) => {
  const R = 6371;                                     // km
  const dLat = toRadians(coord2.lat - coord1.lat);
  const dLng = toRadians(coord2.lng - coord1.lng);
  const a = Math.sin(dLat/2)**2
          + Math.cos(toRadians(coord1.lat)) * Math.cos(toRadians(coord2.lat))
          * Math.sin(dLng/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};
```

Correct, with the formula documented in comments above it (`:30-36`). The
cheapest available source for `core/geo.ts::haversineKm`. Port it and unit-test
it against known distances.

### 4.2 The match-percentage table (`:37-42`) — steal this

| Pickup distance | Drop distance | Match | Meaning |
|---|---|---|---|
| < 2 km | < 2 km | **100%** | very close at both ends |
| < 2 km | < 5 km | **75%** | one end very close, other reasonable |
| < 5 km | < 2 km | **75%** | same, swapped |
| < 10 km | < 10 km | **50%** | same general area |
| > 10 km | > 10 km | **0%** | excluded |

Never implemented, but the **UX idea is better than a raw score**. An admin
reads "92% match" as false precision and distrusts it; banded confidence —
Strong / Fair / Weak — is actionable and honest about its own granularity.

Two places it belongs in commute-os:

- `ui/SuggestionFeed.tsx` — the proposal confidence badge
- `core/policies/zone-confidence.ts` — the de-prioritisation signal

Note the asymmetry is deliberate: 2 km at *one* end plus 5 km at the other still
scores 75%, because one tight end is worth more than two loose ones. That's a
real routing intuition, and it's free.

---

## 5. Why the context is worth more than the code

If this is genuinely a MoveInSync recruitment assignment, it tells you what a
*baseline competent submission* looks like: working auth, working CRUD, a clean
request/approve lifecycle, sensible schemas — and **matching left as a stretch
goal the candidate documented but didn't reach.**

Three signals in one repo:

1. The author **knew** the right answer. They wrote out the haversine formula
   and designed a scoring table — in comments.
2. They shipped a regex instead. Not from ignorance, from running out of runway.
3. The frontend has **no map library at all** (`axios`, `react`, `react-dom`,
   `react-router-dom`). Visualisation never started either.

**That's your calibration.** The thing this candidate ran out of time to build is
exactly what `commute-os` pre-builds: a real matcher, a policy engine, and a map.
Arriving with Clarke-Wright plus nine (now ten) auditable policies puts you well
past the bar this repo represents.

It also validates the design's build order (§18, cut line after step 6): pooling
*logic* is where people stall, not UI. This repo is the empirical evidence for
that ordering.

---

## 6. What to ignore

JWT/bcrypt/cookie auth, CORS config, `logEvents` middleware, all Mongoose
plumbing, the entire React frontend. `rideController.js` is pure CRUD
(`createRide`, `viewMyRides`, `updateRide`, `deleteRide`, `getRideHistory`) with
no matching in it at all.

Also note: the shipped app has **no rider-facing discovery beyond that regex**,
so the product doesn't really function as a carpool app. Don't mine it for
product ideas.

---

## 7. Action list

| # | Change | Where | Effort |
|---|---|---|---|
| 1 | Port haversine + unit-test it | `core/geo.ts` | 15 min |
| 2 | Banded confidence (Strong/Fair/Weak) not a raw % | `ui/SuggestionFeed.tsx` | 30 min |
| 3 | `emergencyContacts?: string[]` on `Employee` | `core/types.ts` | 5 min |
| 4 | Check rider preferences against ride preferences | folded into `skills` (spec 06 §3) | — |

Under an hour of extraction. Then treat the repo as calibration data rather than
source material — it shows you where a competent candidate stalls, and you've
pre-solved that spot.
