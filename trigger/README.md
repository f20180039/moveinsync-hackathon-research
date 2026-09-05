# `trigger/` — Solution 1: Transport Manager, automated daily shift planning

Every morning: load the ride history → compute the day's forecast →
LangChain writes the shift plan → Slack delivers it to the Transport Manager.

Nothing outside this folder is modified. Two pieces of the existing system
are **imported and reused unchanged**:

| Reused | From | Why |
|---|---|---|
| `ingest.load_all` / `ingest.source_for` | `service/signaldesk/ingest.py` | The tolerant DuckDB loader. It normalises the three different `trip_id` formats, converts epoch seconds to ms, and buckets `shift_type` into EARLY/DAY/EVENING/NIGHT. Re-deriving that here would have been a second, worse copy. |
| `delivery.slack_send` | `service/signaldesk/delivery.py` | The existing Slack channel: reads `SLACK_WEBHOOK_URL`, posts `{"text": ...}`, never raises. No new Slack integration was written. |
| `model.BASE_URL` / `model.MODEL` | `service/signaldesk/model.py` | The Sarvam endpoint and model name, so a change there carries here. |
| `constants.ON_TIME_GRACE_MIN`, `MIN_ROWS_PER_SLICE` | `service/signaldesk/constants.py` | On-time is measured exactly as the rest of the repo measures it. |

## Files

| File | Does |
|---|---|
| `config.py` | Every env knob, and the data-directory resolver |
| `stats.py` | Loads the feeds and computes the forecast inputs |
| `schema.py` | `ShiftPlan` / `ShiftBlock` — the structured output |
| `chain.py` | The LangChain chain, plus the deterministic fallback |
| `format.py` | Renders the plan as the Slack message |
| `run_daily.py` | The morning job (entry point) |
| `scheduler.py` | Optional stdlib "fire at 06:30" loop |
| `selftest.py` | End-to-end check, no network, posts nothing |

## Run it

```bash
pip install -r trigger/requirements.txt      # langchain-core, langchain-openai
python -m trigger.selftest                   # 12 checks, no network, no post
python -m trigger.run_daily --dry-run        # full run, prints, does not post
python -m trigger.run_daily                  # full run, posts to Slack
python -m trigger.run_daily --date 2026-07-29 --dry-run   # plan a specific day
```

Schedule it with whatever already runs on the box — the repo has no
scheduling framework to reuse, so none was added:

```cron
30 6 * * *  cd /path/to/repo && .venv/bin/python -m trigger.run_daily >> /var/log/shiftplan.log 2>&1
```

or, to keep it inside a running process: `python -m trigger.scheduler`.

## Environment

Existing variables, already in `.env` — reused, never redefined:

- `SLACK_WEBHOOK_URL` — where the plan is delivered
- `SARVAM_API_KEY` — the LLM; without it the job still ships the
  deterministic plan
- `SIGNALDESK_DATA` — the dataset. The committed value (`../data/fixture`)
  does not exist in the tree, so `config.resolve_data_dir()` falls back to
  `data/sample` rather than crashing.

Optional `TRIGGER_*` variables, all with working defaults:

| Variable | Default | Meaning |
|---|---|---|
| `TRIGGER_DATA` | — | Override the dataset directory |
| `TRIGGER_HISTORY_DAYS` | `28` | History behind the forecast |
| `TRIGGER_TARGET_DATE` | day after the last trip | Plan a specific date |
| `TRIGGER_TZ_OFFSET_MIN` | `330` | Local clock the plan is written in |
| `TRIGGER_PEAK_HOURS` | `3` | How many peak hours to name |
| `TRIGGER_CAPACITY_BUFFER_PCT` | `10` | Standby vehicles above forecast |
| `TRIGGER_RUN_AT` | `06:30` | Fire time for `scheduler.py` |
| `TRIGGER_MODEL` | `signaldesk.model.MODEL` | Model id |
| `TRIGGER_BASE_URL` | `signaldesk.model.BASE_URL` | OpenAI-compatible endpoint (point it at a local or proxied server without touching code) |
| `TRIGGER_MAX_TOKENS` | `16000` | Completion ceiling |
| `TRIGGER_TEMPERATURE` | `0.2` | Sampling temperature |
| `TRIGGER_DRY_RUN` | `false` | Build the message, never post |

## How the forecast works

1. **Window.** The day planned for is the day after the last scheduled trip
   in the data (the same replay convention `api.startup` uses), so a re-run
   of the same dataset always plans the same morning. History is the
   preceding 28 days.
2. **Level — seasonal naive.** The mean of the last four *matching
   weekdays*. A Sunday is forecast from Sundays: in `data/sample` a Sunday
   runs ~2 trips against a weekday's ~50, and a plain trailing average
   over-rosters the weekend by an order of magnitude.
3. **Trend.** The last 14 days over the 14 before them, clipped to ±20%, so
   one holiday week cannot swing the roster.
4. **Split.** Each hour's and each shift-band × direction's historical
   *share of the day* is applied to the forecast total, giving per-block
   trips, employees and vehicles. The profile is taken from matching
   weekdays when there are at least two, otherwise from all days — the
   message says which.
5. **Vehicles.** One trip is one vehicle dispatch in this dataset (there is
   no separate fleet feed), plus the standby buffer.
6. **LangChain.** The aggregates — never a trip row, never a `trip_id` —
   go to `ChatPromptTemplate | ChatOpenAI(Sarvam) | PydanticOutputParser`,
   which returns a `ShiftPlan`. The model is told, in the system prompt, that
   every number it may use is already in the context and it must not compute
   a new one; the arithmetic is Python's, the prose and the allocation
   judgement are the model's.
7. **Fallback.** No key, an unreachable model, or output that will not parse
   → `chain.fallback_plan` builds the same `ShiftPlan` structure straight
   from the forecast. The Slack footer always names which path wrote it. A
   deterministic plan beats a missing one at 06:30.

## What the data does and does not support

The dataset has **no cancellation flag**. "Failed rides" is therefore
reported as the things the columns actually carry — no-show headcount,
`delay_reason` other than `NODELAY`, driver/cab non-compliance, and riders
whose `boarding_status` is not `Boarded` — rather than inventing a
cancellation rate. ETA is `delay_minutes`, MoveInSync's own measurement,
compared against `ON_TIME_GRACE_MIN` from `constants.py`.
