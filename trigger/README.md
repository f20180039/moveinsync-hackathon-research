# `trigger/` — automated LangChain agents

Three agents, one shared spine. Nothing outside this folder is modified.

| Agent | Runs | Asks |
|---|---|---|
| **Transport Manager** (`shift_planning_TransportManager/`) | once each morning | *what should tomorrow's roster be?* |
| **Team Manager** (`delay_management_TransportManager/`) | every few minutes | *which rides need me right now?* |
| **Facilities Head** (`vendor_strategy_Facilities_Head/`) | daily / monthly / quarterly | *are we getting value from these vendors, and what next?* |

## Structure

```
trigger/
├── requirements.txt              the ONE dependency file for both agents
├── README.md
├── run_daily.py                  back-compat shim → shift_planning_TransportManager.run_daily
├── selftest.py                   back-compat shim → shift_planning_TransportManager.selftest
│
├── common/                       shared by both agents
│   ├── config.py                 env knobs, BaseConfig, data-directory resolver
│   ├── data.py                   DuckDB connection via signaldesk.ingest + trip_ops view
│   ├── llm.py                    the LangChain model factory (Sarvam, OpenAI-compatible)
│   ├── slack.py                  wraps signaldesk.delivery.slack_send, adds paging
│   └── state.py                  lightweight JSON dedup store (NEW / UPDATED / REPEAT)
│
├── shift_planning_TransportManager/            Solution 1 — daily shift planning
│   ├── config.py                 forecast knobs
│   ├── stats.py                  loads feeds, computes the forecast inputs
│   ├── schema.py                 ShiftPlan / ShiftBlock
│   ├── chain.py                  the LangChain chain + deterministic fallback
│   ├── format.py                 renders the Slack message
│   ├── run_daily.py              the morning job
│   ├── scheduler.py              optional stdlib "fire at 06:30" loop
│   └── selftest.py               12 checks, no network
│
└── delay_management_TransportManager/                 Solution 2 — escalation & delay management
    ├── config.py                 escalation thresholds
    ├── rides.py                  THE RIDE ADAPTER — the only static-data-aware file
    ├── delay_analyzer.py         deterministic metrics, factors, severity floor
    ├── escalation_agent.py       LangChain reasoning, one call per ride
    ├── schema.py                 Escalation
    ├── format.py                 renders the Slack escalation message
    ├── run_escalations.py        the job
    └── selftest.py               26 checks, no network
```

## Reused, never rebuilt

| Reused | From | Why |
|---|---|---|
| `ingest.load_all` / `source_for` | `service/signaldesk/ingest.py` | The tolerant DuckDB loader: normalises three different `trip_id` formats, epoch seconds → ms, `shift_type` → EARLY/DAY/EVENING/NIGHT. |
| `delivery.slack_send` | `service/signaldesk/delivery.py` | The existing Slack channel: reads `SLACK_WEBHOOK_URL`, posts `{"text": ...}`, never raises. **No second Slack integration exists.** |
| `model.BASE_URL` / `model.MODEL` | `service/signaldesk/model.py` | Sarvam's endpoint and model id. |
| `constants.ON_TIME_GRACE_MIN`, `SLA_BREACH_MS`, `MIN_ROWS_PER_SLICE` | `service/signaldesk/constants.py` | On-time and breach mean here what they mean everywhere else in the repo. |

## Run

```bash
pip install -r trigger/requirements.txt

# Transport Manager
python -m trigger.shift_planning_TransportManager.selftest
python -m trigger.shift_planning_TransportManager.run_daily --dry-run
python -m trigger.run_daily --dry-run                 # old command, still works

# Team Manager
python -m trigger.delay_management_TransportManager.selftest
python -m trigger.delay_management_TransportManager.run_escalations --scan          # find a good demo moment
python -m trigger.delay_management_TransportManager.run_escalations --dry-run --now "2026-07-22 23:15"
python -m trigger.delay_management_TransportManager.run_escalations                 # posts to Slack
```

Schedule with whatever already runs on the box — the repo has no scheduling
framework to reuse, so none was added:

```cron
30 6  * * *  cd /path/to/repo && .venv/bin/python -m trigger.shift_planning_TransportManager.run_daily
*/10 * * * *  cd /path/to/repo && .venv/bin/python -m trigger.delay_management_TransportManager.run_escalations
```

## Environment

Existing variables, reused as-is: `SLACK_WEBHOOK_URL`, `SARVAM_API_KEY`,
`SIGNALDESK_DATA`. The committed `SIGNALDESK_DATA` points at
`../data/fixture`, which is not in the tree, so `resolve_data_dir()` falls
back to `data/sample` rather than crashing.

Shared, all optional: `TRIGGER_DATA`, `TRIGGER_TZ_OFFSET_MIN` (330),
`TRIGGER_MODEL`, `TRIGGER_BASE_URL`, `TRIGGER_MAX_TOKENS` (16000),
`TRIGGER_TEMPERATURE` (0.2), `TRIGGER_DRY_RUN`.

Transport Manager: `TRIGGER_HISTORY_DAYS` (28), `TRIGGER_TARGET_DATE`,
`TRIGGER_PEAK_HOURS` (3), `TRIGGER_CAPACITY_BUFFER_PCT` (10),
`TRIGGER_RUN_AT` (06:30).

Team Manager: `TEAM_NOW`, `TEAM_LOOKAHEAD_MIN` (45), `TEAM_LOOKBACK_MIN` (60),
`TEAM_ETA_DEVIATION_MIN` (15, from `SLA_BREACH_MS`), `TEAM_DRIVER_LATE_MIN` (10),
`TEAM_PICKUP_SLIP_MIN` (10), `TEAM_NOSHOW_LEGS_MIN` (2),
`TEAM_MAX_ESCALATIONS` (8), `TEAM_SEND_REPEATS` (false), `TEAM_STATE_PATH`.

---

# Facilities Head agent — vendor strategy

Three triggers over ONE deterministic metric engine. `metrics.py` and
`scorecard.py` own every number; the model interprets and recommends.

```bash
python -m trigger.vendor_strategy_Facilities_Head.selftest        # 29 checks
python -m trigger.vendor_strategy_Facilities_Head.daily.run     --dry-run --date 2026-07-31
python -m trigger.vendor_strategy_Facilities_Head.monthly.run   --dry-run --month 2026-07
python -m trigger.vendor_strategy_Facilities_Head.quarterly.run --dry-run
```

```cron
30 21 * * *   ... daily.run          # end of operations
0  7  1 * *   ... monthly.run        # first morning of the new month
0  8  1 1,4,7,10 *  ... quarterly.run
```

## The scoring model (deterministic, and argued with rather than guessed at)

| Dimension | Built from | Weight |
|---|---|---|
| **Service** | 0.45 on-time % + 0.30 SLA adherence + 0.15 completion + 0.10 rider rating (renormalised when unrated) | 0.40 |
| **Reliability** | 0.50 consistency (100 − 2 × stdev of daily on-time) + 0.30 good-day share + 0.20 operational cleanliness (no-shows, alerts, driver non-compliance) | 0.30 |
| **Cost value** | peer-relative around the median **cost per on-time trip**: 50 at the median, 100 at half it, 0 at twice it | 0.30 |

Cost per *on-time* trip, not cost per trip — a vendor running cheap trips
late is paying for all of them and delivering some of them. Cost value is
centred at 50 by construction, so overall scores sit below service scores:
it is a ranking instrument, not an absolute grade. Days with fewer than 3
trips are excluded from the consistency series; one trip at 0% is one trip,
not a bad day.

**Trend is never averaged away.** The window is split into its own parts
(months in a quarter, thirds of a month) and the first is compared with the
last: 95% → 91% → 83% reads DETERIORATING even though the average is a
healthy 89.7%.

**Confidence is deterministic** — from trips, periods with data and cost
coverage. The model may lower it and may never raise it.

## What the model may and may not decide

| Python decides | The model decides |
|---|---|
| every figure | what happened, and why it matters |
| the score and the rank | how several metrics add up strategically |
| the recommendation FLOOR | the narrative, strengths, concerns, the action |
| the confidence ceiling | the executive framing |
| the strategy buckets | the risks worth naming |

Guards, re-applied after parsing: the verdict is re-bound to the right
vendor; a recommendation outside the fixed vocabulary falls back to the
floor; the model may move a verdict at most ONE notch along
`INCREASE → PREFERRED → CONTINUE → MONITOR → REVIEW → REDUCE → REPLACE`;
confidence is clamped to the deterministic level; and the next-quarter
strategy lists are rebuilt from the final verdicts, so they can never
contradict the recommendations printed above them.

## What the dataset supports — and what it does not

Supported: trips, on-time, SLA adherence, delay distribution and reasons,
driver/cab non-compliance, riders planned vs actual, no-shows, dashboard
cancellations, alerts with severity, rider ratings, vendor cost
(`bill.trip_cost`, 99.9% joined), distance.

**Not in the data, and never referenced:** contracted SLA targets, contract
terms, penalty clauses, complaint tickets, vendor fleet size, quoted rates.
Every report says so in its footer, and the selftest asserts the body never
uses that language.

## The quarter, honestly

The sample holds three whole months — 2026-05, 2026-06, 2026-07 — which is
not a calendar quarter (Q2 would hold two of them, Q3 one). The default is
therefore the **last three consecutive months present**, labelled
`2026-05..2026-07` and described as a rolling quarter in the report itself.
`--quarter 2026Q2` forces the calendar one and says which months were
missing. No rows were invented to fill a calendar quarter out.

## Live data

Same as the other two agents: the swap point is the data layer.
`common/data.py` hands `metrics.py` a DuckDB connection; against a live
system that becomes a warehouse connection or an API-backed view exposing
the same columns. `metrics.py`, `scorecard.py`, `analysis.py`, the three
runners and the Slack path do not change. Triggers move from cron to the
warehouse's own schedule or a close-of-day event.

---

# Team Manager agent

## End to end

```
run_escalations
   ↓  rides.StaticCsvRideSource      pick a simulated "now", load rides in scope
   ↓  delay_analyzer.find_escalations deterministic factors + severity floor
   ↓  common.state.SeenStore          NEW / UPDATED / REPEAT — drop repeats
   ↓  escalation_agent.reason         ONE LangChain call per ride, in parallel
   ↓  format.messages                 one Slack message, worst first, paged if long
   ↓  common.slack.send_all           signaldesk.delivery.slack_send
```

## What triggers an escalation

Every threshold is env-tunable; every figure is computed in Python.

| Factor | Condition | Source columns |
|---|---|---|
| `ETA_DEVIATION` | expected arrival ≥ 15 min later than planned | `planned_end_epoch`, projected or actual arrival |
| `OVERDUE` | in flight and ≥ 15 min past planned arrival | `planned_end_epoch` vs now |
| `DRIVER_LATE_START` | driver started ≥ 10 min after schedule | `actual_start_epoch` − `planned_start_epoch` |
| `DRIVER_CAUSE` | MoveInSync attributes the delay to the driver | `delay_reason = 'DRIVER'` |
| `DRIVER_NON_COMPLIANCE` / `CAB_NON_COMPLIANCE` | flagged on the trip | `is_driver_nc`, `is_cab_nc` |
| `PICKUP_SLIP` | worst rider pickup ≥ 10 min behind | `emp_legs.actual_pickup_epoch` − `planned_pickup_epoch` |
| `LATE_BOOKING` | riders added outside the planned roster | `emp_legs.signintype = 'Adhoc'` |
| `BOOKING_CANCELLED` | booking pulled after the trip formed | `not_boarding_reason = 'TRIP_CANCELLED_FROM_DASHBOARD'` |
| `NO_SHOW_IMPACT` | ≥ 2 riders did not travel | `not_boarding_reason = 'NO_SHOW'` |
| `SAFETY_ALERT` | any alert on the trip | `alerts.event_type`, `severity` |
| `CAPACITY_OVERFLOW` | more riders than seats | `actualemployee_cnt` vs `actual_cab_capacity` |

Severity floor: `CRITICAL` for a panic alert, `Sev-1`, or ≥45 min slip;
`HIGH` for ≥30 min, `Sev-2`, a ≥20 min late start, or 3+ factors; `MEDIUM`
for ≥15 min, a ≥10 min late start, or 2 factors; `LOW` otherwise.

A slip beyond 24 hours is corrupt data, not a late cab — the sample carries a
trip whose `actual_start` is ~58 days from its schedule. Those become a data
caveat on the ride, never an "83,481 minute delay" in Slack.

## Deterministic vs LLM

| Python (`delay_analyzer.py`) | The model (`escalation_agent.py`) |
|---|---|
| every minute figure | what actually happened, in words |
| which thresholds were crossed | the likely cause when several factors collide |
| how many factors a ride has | severity, at or above the floor |
| the severity floor | whether the Team Manager must act now |
| data-quality caveats | the concrete recommended action |

`delay_minutes` is **overwritten** with the computed value after parsing, so
a model slip cannot put a wrong number in front of a manager. Severity is
clamped to the floor. The model never sees a raw row, a `trip_id` join or an
employee id — only the computed picture.

## Multiple rides

Each flagged ride is its own chain invocation, dispatched through
`chain.batch(..., max_concurrency=4, return_exceptions=True)`. Four
problematic rides produce four independent pieces of reasoning, not one
blended paragraph. A ride whose call fails or whose JSON will not parse falls
back to its deterministic escalation; the others are unaffected, and the
footer reports `mixed` when both paths fired in one run. `TEAM_MAX_ESCALATIONS`
(8) caps how many reach the model in a single run, worst first.

## Slack

Option A: one message per run, ranked worst first, each ride its own block.
If the run would exceed Slack's ~4k limit, `common.slack.chunk` pages it into
`part 1 of 2` rather than truncating an escalation. Delivery is
`signaldesk.delivery.slack_send`, unchanged.

## Spam control

`common/state.py` writes one JSON file (`trigger/.state/`, git-ignored).
Each escalation has a fingerprint: sorted factor codes + severity + delay
rounded to a 10-minute bucket.

- **NEW** — never escalated → notify
- **UPDATED** — fingerprint changed (got worse, or a new factor) → notify
- **REPEAT** — identical situation → suppressed, counted in the footer

State is only recorded after Slack accepts the message, so a failed delivery
does not silence the next run. `--reset-state` clears it.

## Static data: the assumptions, stated

1. **There is no live feed.** The agent picks a moment *inside* the data and
   treats it as now — by default the busiest in-flight quarter-hour in the
   last week of data. `TEAM_NOW` overrides it; `--scan` reports which moments
   carry the most escalations.
2. **No future information is used.** For a ride still in flight,
   `actual_end_epoch` is the future: the expected arrival is *projected* from
   the driver's actual start plus the planned duration, and the ride carries
   `etaBasis: projected`. A finished ride uses its real arrival
   (`observed`). A ride that has not started reports no actual start at all.
3. **There is no booking timestamp in the dataset.** `signintype = 'Adhoc'`
   (a rider added outside the planned roster) and
   `TRIP_CANCELLED_FROM_DASHBOARD` are the only booking-lateness signals
   available, and they are labelled as proxies, not as a booking clock.
4. **Alerts have no live state.** Every alert in the sample is `CLOSED`;
   they are treated as "an alert fired on this ride", not as an open incident.
5. **39 trip_ids appear on more than one row.** `trip_ops` keeps one row per
   id — an unguarded join pairs one row's schedule with another's actual
   start and manufactures delays that never happened.

## Live data: what changes

**One file.** `rides.py` holds the only static-data knowledge in the agent.
A live source implements the same two methods:

```python
class LiveRideSource:
    def now_ms(self) -> int:                 # real clock
    def rides_in_scope(self) -> list[dict]:  # same RideContext keys
```

and fills `expectedArrivalLocal` from the *reported live ETA* with
`etaBasis: "reported"` instead of projecting it. `delay_analyzer`,
`escalation_agent`, `format`, `state` and the Slack path are untouched.

| | Static (today) | Live |
|---|---|---|
| Trigger | cron every N minutes | ride event / ETA update |
| Clock | simulated moment in the data | wall clock |
| ETA | projected from actual start | reported by the driver app |
| Scope query | rows around the simulated now | the rides the event touched |
| Dedup | JSON file | same, or Redis for multi-worker |

## Worked examples

**Late booking** — Ride 1252013, 4 riders, one joined `Adhoc`; worst pickup
12 min behind. → `LATE_BOOKING` + `PICKUP_SLIP`, 2 factors → floor MEDIUM →
the model reads both and reports the pickup slip as downstream of the roster
change, not as a driver failure → *"Confirm the roster with the booking
desk"* → one MEDIUM block in the run's Slack message.

**ETA worsening after the driver starts** — Ride 3452262 in flight: driver
started on time, but at `now` it is 20 min past its planned arrival and the
projected arrival is 14:15 against a planned 13:55. → `ETA_DEVIATION` +
`OVERDUE` → MEDIUM → the model distinguishes "started fine, deteriorated in
transit" from a late start → *"Call the driver, confirm whether the arrival
can be held, warn the site if not."*

**Driver-side delay** — Ride 3433776: driver started 22:10 against a
scheduled 22:00, worst pickup 13 min behind. → `DRIVER_LATE_START` +
`PICKUP_SLIP` → MEDIUM → cause attributed to the driver's start, not traffic
→ *"Contact the vendor about this driver's start time."*

**Multiple contributing factors** — Ride 3431731: 22 min arrival slip, 10 min
late start, 10 min pickup slip. Three factors → floor HIGH → the model names
the late start as the primary cause and the rest as consequences, rather than
listing three equal problems.

**Multiple simultaneous escalations** — the demo moment
(`--now "2026-07-22 23:15"`) yields 7: 4 HIGH, 2 MEDIUM, 1 LOW, spanning ETA
deviation, driver delay, pickup slip and a `WOMAN_TRAVELLING_ALONE` alert.
Seven independent model calls, one Slack message in two parts, worst first.
