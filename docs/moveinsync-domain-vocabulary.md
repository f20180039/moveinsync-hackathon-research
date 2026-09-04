# MoveInSync's own vocabulary — read this before naming anything

**Compiled 2026-09-04** from MoveInSync's public help centre, because the sample
dataset does not arrive until 10:00 on build day and several column names in our
spec were guesses.

**Why this matters beyond correctness.** The judges are MoveInSync. Using *their*
words for their own concepts — marshal, OTA/OTD, DRT, no-show, dark hours — is
free credibility, and using invented words for concepts they already have a name
for is a small, avoidable signal that we did not look.

Every definition below is quoted or closely paraphrased from the sources at the
bottom. **Where this file and the design spec disagree, this file is closer to
reality** — the spec was written against the problem statement's *indicative*
column list, which the statement itself says is indicative.

---

## 1. The corrections that matter most

### `marshal`, not `night_escort` — and our night window is wrong

The design spec invented a `night_escort` boolean because §3.1's indicative
columns had no escort field (plan deviation 6). **MoveInSync's actual term is
"marshal."**

- A **"Marshal Required"** banner shows in the driver app, and "the female or
  special needs employee will not be allowed to board before a marshal signs in
  on the device."
- There are **three states**, not a boolean:
  - **Marshal Required**
  - **Marshal Maybe Required** — shown "if the first pick up male employee or the
    last drop male employee is marked no show"
  - **Good to go** — no marshal needed
- **"Dark hours" are configured per city**, and the example given is
  **19:00 to 06:00** — *"Each city can have its own dark hours configured to
  align with local transport safety policies."* When a booking falls inside the
  configured dark hours and matches a booking type requiring marshal assignment,
  **the system auto-enables the marshal toggle.**

**What this changes for us:**

1. Rename the concept to **marshal**. `marshal_required` / `marshal_signed_in`.
2. **The night window must be config, not a constant, and the default should be
   19:00–06:00 — not the 22:00–06:00 our `constants.py` hardcodes.** Ours was a
   guess and it is three hours too narrow. Per-*site* dark hours is also the
   honest multi-tenancy story, and it is nearly free: the thresholds are already
   in one module.
3. `marshal_compliance` beats `night_compliance` as a metric name, and the
   interesting figure is **marshal *signed in* where marshal was *required***.
   "Maybe Required" is a genuinely uncertain third state — a good fit for the
   confidence machinery rather than something to flatten into a boolean.

### OTA and OTD are two different metrics, split by direction

- **OTA = On-Time Arrival**, and it applies to **login trips**.
- **OTD = On-Time Departure**, and it applies to **logout trips**.

Our spec has a single `ota` metric with `direction` as a slice dimension. That is
not wrong arithmetically, but it means the console says "on-time arrival, logout"
which is not a thing. **Name them `ota` (login) and `otd` (logout)** and let each
filter its own direction. The problem statement's own worked example is "OTA is
78%", so getting this pair right lands immediately.

### Delay attribution already exists, with a defined precedence

This is the big one for the root-cause decomposition task. MoveInSync classifies
every delay into one of four buckets, **checked in this order**:

> **Trip Delay → Driver Delay → Employee Delay → Traffic Delay**

- **Driver Delay** — the system compares the driver's arrival at the first
  employee pickup against that employee's planned sign-in time; if **Driver
  Reporting Time (DRT)** exceeds the first employee's planned sign-in plus a
  **grace time**, it is a driver delay.
- **Employee Delay** — if the driver was not delayed, and the *actual* pickup
  time exceeds the *planned* pickup time plus an **employee grace time**.
- **Traffic Delay** — the residual: anything that is neither of the above.

**What this changes for us:** the root-cause decomposition (plan Task 8) should
decompose an OTA/OTD shortfall **by this taxonomy first**, and by
vendor/site/shift second. "OTA is 7 points below trend; 4.1 of those points are
driver delay, concentrated in two vendors" is a sentence a MoveInSync transport
manager already thinks in. Decomposing only by vendor answers a weaker question.

Note the precedence is a **cascade, not a partition of independent causes** — a
trip is attributed to exactly one bucket, and the order decides ties. If the real
dataset carries a delay-reason column, map it onto these four rather than
inventing categories. Our fixture's `reason_code` values
(`TRAFFIC`, `DRIVER_LATE`, `VEHICLE_BREAKDOWN`, `WEATHER`, `GATE_HOLD`) are a
reasonable stand-in but are **not** their taxonomy.

### There are four distance fields, not two

| Field | Definition (theirs) |
|---|---|
| **Planned Km** | "The shortest/fastest (configurable) distance calculated based on the routed employees on the trip using the distance stored in the MIS system." |
| **Reference Km** | "The fastest route (as per google) which is calculated at the time when the system receives the trip end time based upon the waypoints of the employees picked in a trip/route." |
| **Actual Km** | "The distance recorded by the device in which the trip was performed. **In cases of GPS loss the actual Km will not be calculated.**" |
| **Map Km** | The Google fastest route computed *on demand* when you click the Map Km option. |

**What this changes for us — two things.**

1. **`reference_km` is a reference point that ships with the data.** The mandatory
   requirement is contextualising a metric against a reference point, and
   `actual_km / reference_km` is a route-efficiency metric whose reference is
   *given*, not derived. That is a cheap seventh metric with an unusually strong
   justification, if there is time.
2. **GPS loss causes missing `actual_km`.** Our fixture plants GPS gaps and
   missing close-outs as two *independent* faults. In reality they are
   **correlated** — a trip with a GPS hole is a trip whose actual distance was
   never computed. When the real data arrives, expect `actual_km` nulls to
   cluster on the GPS-gap trips, and say so in the data-quality panel. That
   correlation is a better story than two unrelated defect rates.

---

## 2. Vocabulary worth using, and the metrics it suggests

| Their term | What it is | Metric potential |
|---|---|---|
| **No-Show** | "Employee Marked No-Show by Driver/System" | A no-show rate per site/shift is real, named, and cheap. It also feeds "Marshal Maybe Required". |
| **DRT — Driver Reporting Time** | When the driver reported at the first pickup; "used to cross-verify when the driver picked up the desired employee", and the input to OTA/OTD delay classification | The field that makes driver-vs-employee delay attribution possible at all. |
| **Auto Sign-off** | Trips the system closes itself, with a recorded **geocode and distance from office** | **This explains our "unclosed trip" fault.** A trip with no `actual_at` is usually one auto-sign-off didn't catch. Distance-from-office on the sign-off geocode is a data-quality signal. |
| **Adhoc trip** | A trip created by the system rather than rostered | Rostered-vs-adhoc share is an ops-cost signal; adhoc trips also have their own marshal enforcement. |
| **GPS loss** | A flagged trip condition, with its own "how to identify" article | Our confidence figure's headline input. |
| **Driver Duty Hours** | Tracked including rest time | A safety/compliance metric. Real, and the kind of thing a facilities head escalates on. |
| **Marshal dashboard** | An existing operator surface | Worth knowing it exists so we do not claim to have invented the concept. |
| **Male Buddy** | A related safety feature | Context for how seriously they treat the marshal flow. |
| **signInOtp / signOutOtp** | OTPs verifying trip start and end | Trip-integrity signals. |
| **mBearing** | Vehicle heading in degrees, on tracking payloads | GPS trace realism. |

**One confirmation worth having:** their tracking API takes time in **epoch
milliseconds**, which is exactly what our spec chose. That guess was right.

---

## 3. What we could not find

**There is no public MoveInSync hackathon dataset.** I searched their site, their
help centre, Kaggle and GitHub. Nothing published, which is unsurprising for a
private company handling client commute data — and the statement calls it
"anonymised", implying it is generated or scrubbed for the event rather than
lifted from production.

The nearest public analogues (Kaggle transport/logistics tracking sets) carry
none of the vendor-performance, marshal, or delay-attribution structure that
makes this problem what it is. **They are not worth adapting.** Our committed
fixture is closer to the described shape than anything public, because it was
built from the statement's own §6 column list.

**So the plan does not change: ingest stays schema-tolerant, metric SQL stays
declarative, and 10:00 is a config change.** What this research buys is not a
dataset — it is the right *names*, and a correction to two things we had guessed
wrong.

---

## 4. The first ten minutes tomorrow

When the dataset lands, before writing any metric SQL:

1. `head -3` every file and **post the real column headers to the team channel
   immediately** — the plan already names this as the one thing to do first.
2. Diff the real columns against this file. Specifically look for: `marshal`
   (any spelling), `no_show`, `drt` / `driver_reporting_time`, `reference_km`,
   `map_km`, `auto_signoff`, `adhoc`, `gps_loss`, and a delay-reason column.
3. **Set the dark-hours window from whatever the data supports**, defaulting to
   19:00–06:00 rather than our 22:00.
4. If a delay-reason column exists, map its values onto Driver / Employee /
   Traffic before building the decomposition.
5. Where a column we assumed is absent, the metric that needs it must **degrade
   to low confidence, not fail** — that path already exists and is tested.

---

## Sources

- [Type of KM data captured in MoveInSync system](https://helpcenter.moveinsync.com/support/solutions/articles/1070000093241-type-of-km-data-captured-in-moveinsync-system)
- [Trip Information (article index)](https://helpcenter.moveinsync.com/support/solutions/1070000145529)
- [OTA delays logic for login trips (Driver, employee, traffic delays)](https://helpcenter.moveinsync.com/support/solutions/articles/1070000084989-ota-delays-logic-for-login-trips-driver-delays-employee-delays-traffic-delays-)
- [OTA-OTD delays (folder)](https://helpcenter.moveinsync.com/support/solutions/folders/1070000398052)
- [Driver Reporting Time — Current Logic](https://helpcenter.moveinsync.com/support/solutions/articles/1070000086489-driver-reporting-time-current-logic)
- [Driver Reporting Time (DRT) — Easy Explanation](https://helpcenter.moveinsync.com/support/solutions/articles/1070000137670-driver-reporting-time-drt-easy-explanation)
- [What are the conditions for a trip to require marshal](https://helpcenter.moveinsync.com/support/solutions/articles/1070000131364-what-are-the-conditions-for-a-trip-to-require-marshal)
- [All about Marshal Required Trips](https://helpcenter.moveinsync.com/support/solutions/articles/1070000102257-all-about-marshal-required-trips)
- [Rentlz Marshal Feature](https://helpcenter.moveinsync.com/support/solutions/articles/1070000137779-rentlz-marshal-feature)
- [Rentlz Booking Management API](https://helpcenter.moveinsync.com/support/solutions/articles/1070000134486-rentlz-booking-management-api)
- [Types of Bookings & Trips](https://helpcenter.moveinsync.com/support/solutions/articles/1070000137700-types-of-bookings-trips)
- [Employee Transport Management System (product overview)](https://moveinsync.com/employee-transport-management-system/)
- [Monthly employee commute data checklist](https://moveinsync.com/blog/employee-commute-data-checklist)
