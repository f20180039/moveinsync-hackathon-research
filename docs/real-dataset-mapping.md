# The real dataset — what it actually is, and what has to change

**Written 2026-09-04, evening.** The dataset arrived early via Drive and is
downloaded to `data/real/` (572 MB, git-ignored). It ships with a
`Dictionary/` folder documenting every column and every deliberate data quirk —
read `data/real/Dictionary/README.md` first, it is excellent.

**This file is the delta.** Where it disagrees with the spec or the build plan,
**this file wins** — it is derived from the actual data, not from the problem
statement's indicative column list.

The headline: the architecture survives intact, the *schema* does not, one
planned feature has **no data to run on**, and one planned feature just became
nearly free.

---

## 1. The five real feeds

| File | Grain | Rows | Was our |
|---|---|---|---|
| `Ride_data _trip-{may,June,July}_2026.csv` | one trip | 188,992 + 210,669 + 215,885 = **615,546** | `trips` |
| `emp_Data.csv` | one employee's **leg** of a trip | **1,637,906** | `roster` (but far richer) |
| `trip_feedback.csv` | one rider's rating of a leg | **512,873** | `feedback` |
| `bill_data.csv` | one billed line item | **620,942** | `costs` |
| `alerts_data.csv` | one safety/compliance event | **51,699** | *nothing — new* |

`trip_id` is the spine through all five. `stwid` (rider id) additionally links
riders across legs, alerts and ratings.

**Two of our six feeds do not exist.** There is no `gps_pings` file and no
`delays` file — delay is a *column* on the trip row. Drop both from `FEEDS`.

**Note the space in the filename:** `Ride_data _trip-may_2026.csv` has a space
before `_trip`. A naive glob will miss it. Use `Ride_data*trip-*.csv`.

**Volume is ~77× the fixture.** 615k trips vs 8k, 572 MB vs 7.6 MB. DuckDB
handles this without complaint, but the materialise-to-table decision (bug F2)
now matters much more than it did — re-scanning 572 MB on every metric query
would be visibly slow rather than merely wasteful.

---

## 2. ⚠️ Epoch is in SECONDS, not milliseconds

**The single most invasive correction.** The spec says, in bold, "All timestamps
epoch milliseconds". The real data is **epoch seconds**:

- `ride_data_trip`: `planned_start_epoch`, `planned_end_epoch`,
  `actual_start_epoch`, `actual_end_epoch` — comma-formatted **strings** of
  epoch **seconds** (`"1,777,595,400"`)
- `emp_data`: `planned_pickup_epoch`, `planned_drop_epoch`,
  `actual_pickup_epoch`, `actual_drop_epoch` — **floats** of epoch seconds

Everything downstream inherits this. `constants.py`'s `ON_TIME_GRACE_MS`,
`SLA_BREACH_MS`, `IST_OFFSET_MS`, every `Window`, and DuckDB's `epoch_ms()` in
the metric SQL are all wrong by a factor of 1000.

**Resolution: normalise to epoch milliseconds at the ingest boundary**, once, and
leave every downstream layer untouched. `CAST(REPLACE(col, ',', '') AS BIGINT) *
1000`. The alternative — changing the unit everywhere — would touch the schemas,
the registry, the references, the verdict engine and the sweep, and it is exactly
the sort of sweeping change that goes wrong at hour two.

**Do not skip the comma-strip.** `CAST('1,777,595,400' AS BIGINT)` fails in
DuckDB; it does not silently produce a wrong number, which is at least merciful.

---

## 3. ⚠️ There is no free-text feedback — the vernacular pipeline has no data

`trip_feedback` carries **five numeric ratings (0–5)** and nothing else:
`route_rating`, `driver_rating`, `cab_rating`, `safety_rating`,
`marshal_rating`. **No comment column. No language column.**

So **Task 21's translation and sentiment lexicon have nothing to run on.** The
Sarvam translation capability is verified working, but there is no text in this
dataset to translate. `SENTIMENT_LEXICON`, `normalise()`, the parquet cache and
the whole `comment → comment_en → sentiment` path are dead code against the real
data.

**Cut it.** Do not keep it running on synthetic comments alongside real data —
a demo that quietly mixes fabricated rows into a real dataset is the one thing
here that would be genuinely dishonest, and a judge who asks "where did that
Hindi comment come from" gets an answer nobody wants to give.

`experience` becomes ratings-based, which is simpler and better founded:

```sql
-- 0 may mean "unrated" rather than "terrible" -- the dictionary flags this
-- explicitly. Check the distribution before averaging; if 0s are unrated,
-- exclude them rather than dragging every average down.
SELECT avg((route_rating + driver_rating + cab_rating + safety_rating) / 4.0)
FROM trip_feedback f JOIN trips t ON t.trip_id = f.trip_id
WHERE ... AND route_rating > 0
```

**This frees ~45 minutes**, which is roughly what the new ingest work costs. Net
neutral on the clock.

---

## 4. 🎁 The delay taxonomy ships in the data

`ride_data_trip.delay_reason` ∈ **`NODELAY`, `TRAFFIC`, `DRIVER`, `EMPLOYEE`**.

That is *exactly* the taxonomy in
[`moveinsync-domain-vocabulary.md`](moveinsync-domain-vocabulary.md) §1, which I
reconstructed from their help centre before the data arrived. It is a column.

**Task 8's root-cause decomposition becomes a `GROUP BY`.** No derivation, no
DRT reconstruction, no grace-time guessing:

```sql
SELECT delay_reason,
       count(*)                                    AS trips,
       avg(CAST(REPLACE(delay_minutes, ',', '') AS BIGINT)) AS avg_delay_min,
       100.0 * count(*) / sum(count(*)) OVER ()    AS share_pct
FROM trips t
WHERE {window} AND {slice} AND delay_reason <> 'NODELAY'
GROUP BY delay_reason
ORDER BY trips DESC
```

This is the cheapest large win available tomorrow: *"OTA is 7 points below
trend, and 4.1 of those points are driver delay, concentrated in two vendors"* —
in the operator's own vocabulary, straight from their own column.

`delay_minutes` is a comma-formatted string. Strip before arithmetic.

---

## 5. 🎁 Multi-tenancy stops being an argument

**`business_unit` has five values** and appears on **all five feeds**:
`vanta-Aus`, `catalyst-Sac`, `orbit-Slc`, `vanta-Sea`, `pinnacle-Slc`.

The spec listed multi-tenancy enforcement as out of scope and promised a judge
only that "the query layer sits behind an interface". Now it can be
*demonstrated*: add `TENANT` as a dimension, give two business units different
SLA targets in config, and show the same sweep producing different findings for
each. That is the bonus criterion answered with a screen instead of a sentence.

`DARK_HOURS_BY_SITE` is already the right shape for per-tenant config.

---

## 6. Dimension mapping — and one that will bite

| Our `Dimension` | Real column | Cardinality | Notes |
|---|---|---|---|
| `TENANT` *(new)* | `business_unit` | 5 | on every feed |
| `SITE` | `office` | 17 in trips, 19 in emp/bill | counts differ between feeds |
| `VENDOR` | `vendor_id` (trips) / `vendor` (bill) | 23 / 24 | **different column names, and different counts** |
| `MODE` | `product_type` | 3 | `CAB`, `BUS`, `SPOT_2.0` |
| `DIRECTION` | `trip_direction` / `trip_type` | 2 | `LOGIN`, `LOGOUT` — **different column name in feedback** |
| `SHIFT` | `shift_type` | **99–100** | ⚠️ see below |

**`shift_type` is a `HH:MM` shift-start time, not a shift name — 99 distinct
values.** Slicing by it directly produces ~99 slices per metric, which is a wall
of findings nobody reads and a sweep that takes far longer than it should.

**Bucket it** into time-of-day bands before using it as a dimension — e.g.
`EARLY (04:00–07:59)`, `DAY (08:00–15:59)`, `EVENING (16:00–21:59)`,
`NIGHT (22:00–03:59)`. Four buckets, and "night" then lines up with the dark-hours
concept the marshal metric needs.

Also note `vendor_id` vs `vendor` and `trip_direction` vs `trip_type`: the same
concept under different names in different files. Alias at the ingest boundary so
one name reaches the registry.

---

## 7. Marshal compliance — derivable, and better than planned

There is no `marshal_required` column. There is:

- `ride_data_trip.actual_escort` (bool) — whether an escort **was** present
- `alerts_data.event_type` including **`WOMAN_TRAVELLING_ALONE`** and
  **`FIRST_MALE_NO_SHOW`**
- `emp_data.gender` — `MALE` / `FEMALE`
- `trip_feedback.marshal_rating` (0–5)

Those two alert types are precisely the "Marshal Required" and "Marshal Maybe
Required" conditions reconstructed in the vocabulary doc — MoveInSync's system
raises an alert for exactly the situation the policy covers.

**So requirement is derivable rather than declared:** a trip needs an escort when
it runs inside dark hours and carries a female rider (join `emp_data.gender`), or
when a `WOMAN_TRAVELLING_ALONE` alert fired. Compliance is
`actual_escort = true` over that population.

That is a *stronger* metric than the planned one, because the requirement comes
from the operator's own safety rules rather than from a column we invented — and
`WOMAN_TRAVELLING_ALONE` firing on a trip with `actual_escort = false` is about
as sharp a finding as this dataset contains.

---

## 8. Metrics now available cheaply, and worth taking

Beyond the planned six. All are single aggregates over columns that exist.

| Metric | From | Reference point | Why it earns its place |
|---|---|---|---|
| **No-show rate** | `noshow_cnt / plannedemployee_cnt`, or `emp_data.is_no_show` | trend, peer | Real MoveInSync vocabulary; drives capacity waste |
| **Capacity utilisation** | `actualemployee_cnt / actual_cab_capacity` | target | Direct cost lever a facilities head acts on |
| **Driver / cab non-compliance** | `is_driver_nc`, `is_cab_nc` | target 0 | Compliance floor, same hard-target logic as marshal |
| **Sev-1 alert rate** | `alerts_data.severity = 'Sev-1'` per 1k trips | trend, peer | The proactive-safety story, and a genuine spike detector |
| **Alert acknowledgement time** | `acknowledge_time − start_time` | target | An ops SLA that is *about* responsiveness |
| **Cost per km** | `trip_cost / total_trip_km` | peer, trend | Better than cost-per-trip; normalises trip length |
| **Safety rating** | `trip_feedback.safety_rating` | trend | Pairs with the alert rate — a dip plus a spike is a story |
| **EV share** | `actual_cab_fuel_type = 'Electric'` | trend | Sustainability; cheap, and nobody else will show it |

**Do not add all of these.** Tier 1 stays at three or four metrics. But
`no_show_rate` and `sev1_alert_rate` are strong enough to displace weaker
planned ones, and the alerts feed is the most differentiated material in the
dataset — no team ignoring it will produce the proactive-safety narrative.

---

## 9. The data quirks, which are our fault list made real

The dictionary lists these openly and says handling them is rewarded. Our
rejects quarantine, gap register and confidence figure were built for exactly
this — the difference is these are real.

| Quirk | Where | What our design already does |
|---|---|---|
| **`trip_id` in three formats** — `"1,097,076"` / `"1123974"` / `1097349` | comma in trips+alerts+feedback; plain string in bill; `int64` in emp | **Nothing yet. This is the one that must be fixed first** — every join silently returns zero rows otherwise |
| **Dates in four formats** — ISO, `"May 1, 2026"`, `"June 3, 2026, 11:00 AM"` | one per file | Parse per file; do not assume one format |
| **Comma-formatted numerics** — `delay_minutes`, `trip_cost`, all epochs | several | Strip at ingest |
| **dtype drift across months** — `is_driver_nc`/`is_cab_nc` bool vs object; `planned_km` float vs object | May vs Jun/Jul | **`union_by_name` handles this.** It is the reason that flag is in the spec |
| **Negative `planned_km` / `traveled_km`** down to −6.63 | `emp_data` | Physically impossible → count as `null_critical_fields`, which lowers confidence |
| **Stray `"False"`** in `severity` | `alerts_data` | Same — a value outside the enum is a data gap |
| **`total_trip_km = 0.0`** on many rows | `bill_data` | Guard cost-per-km against divide-by-zero; `nullif` |
| **Ratings of `0` may mean "unrated"** | `trip_feedback` | Check the distribution before averaging |
| **Meaningful nulls** — unacknowledged alert, unboarded leg | everywhere | Design for missingness; the dictionary is explicit that these are not errors |

**`stwid = 0` is a placeholder**, not a rider. Filter it from any per-employee
analysis.

---

## 10. What this does to the plan

**Unchanged:** the §1.1 invariant, the four-tier verdict engine, references
(trend/target/peer), ranked findings with `evidence_sql`, the unprompted sweep,
the validated narrative with template fallback, the four tools, Slack + SES
delivery, the replay clock, the cost meter. **The architecture was the right
bet** — none of it depended on the schema.

**Must change, in this order:**

1. **`FEEDS`** → the five real names, and the glob must tolerate the space.
2. **Normalise `trip_id` and the epochs at the ingest boundary.** Strip commas,
   cast, multiply epochs by 1000 so every downstream layer keeps working in ms.
   Alias `vendor`→`vendor_id` and `trip_type`→`trip_direction`.
3. **Point the simulated clock at the end of July 2026**, not the fixture's
   September window. A sweep over a window with no data produces a `DATA_GAP`
   finding and nothing else, and it will look like a bug in the engine.
4. **Bucket `shift_type`** into four time-of-day bands.
5. **Rewrite the metric SQL** against real column names — `actual_end_epoch` vs
   `planned_end_epoch` for OTA/OTD, `delay_reason` for the decomposition.
6. **Cut Task 21's translation**; make `experience` ratings-based.
7. **Add `TENANT`** as a dimension.

**Then re-calibrate.** Every threshold and the pinned tier distribution were
measured against the fixture. On 615k real trips they mean nothing until
re-measured — and the calibration step exists precisely for this.

## 11. First thing tomorrow

The fixture has done its job: the code exists, the contracts are pinned, the
tests pass. Now point `SIGNALDESK_DATA` at `data/real` and let the ingest tests
tell you what breaks. **Expect the reject count to be large on the first run** —
that is the quarantine working, and reading `reject_errors_*` is the fastest
schema documentation there is.

Keep the fixture. It stays the deterministic input for the test suite, so the
suite keeps running offline and fast while the real data drives the demo.
