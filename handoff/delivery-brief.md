# Brief: delivery (Slack + email), then the deck

You own two files and one folder. Your morning job is small and finishes early
on purpose — **your afternoon job is the deck and the demo script, and that is
scored.**

| Yours | Path |
|---|---|
| Delivery channels | `service/signaldesk/delivery.py` |
| Its tests | `service/tests/test_delivery.py` |
| Deck, demo script, screenshots | `deck/` |

Do not edit anything else under `service/signaldesk/` — Anshuman is working
there and merge conflicts today are expensive.

---

## Part 1 — delivery (target: done by 12:00)

### What it does

The agent finds problems, ranks them, writes a short brief, and **actually
sends it**. Not a draft in a queue — a real message in a real Slack channel and
a real email. That is the difference between a demo and a mockup, and it is the
last step of the loop.

Routing is by severity, and it is already decided:

| Worst finding for that reader | Goes to |
|---|---|
| `BREACH` or `CONCERN` | Slack **and** email |
| `WATCH` | Slack only |
| `PASS` | neither — console only |

### The contract you write against

```python
# Someone else writes these; you consume them.
# A Finding has: tier ('PASS'|'WATCH'|'CONCERN'|'BREACH'), id, metric_id,
#   observed, gap, confidence, audiences
# A SweepRun has: run_id, findings, feed_health, window

def slack_send(subject: str, body: str) -> DispatchResult: ...
def ses_send(subject: str, body: str) -> DispatchResult: ...

@dataclass(frozen=True)
class DispatchResult:
    channel: str        # "slack" | "email"
    delivered: bool
    detail: str         # "ok", or the reason it failed — NEVER the webhook URL

def dispatch(run, compose_fn) -> list[DispatchResult]: ...
```

`compose_fn(run, audience) -> str` is handed to you. **Do not write the brief
text** — that lives in `compose.py` and is someone else's file.

### Slack

One `POST` with `{"text": "..."}` to `$SLACK_WEBHOOK_URL`. Use `httpx` (already
installed). Slack renders its own markdown in that field, so `*[BREACH]*` comes
out bold and triple-backticks give you a code block.

**Skip Block Kit.** It is a rabbit hole and buys nothing when the brief is
already prose.

### Email

`boto3` SES `send_email`. `SES_FROM` and `SES_TO` (comma-separated) from the
environment. SES is in **sandbox**, which means it delivers *only* to
pre-verified addresses.

**If SES is not configured, return `DispatchResult("email", False, "not
configured")` and carry on.** Do not raise, do not retry, do not crash the
sweep. Slack is the primary channel; email is a second proof. An unconfigured
email channel is a supported state, not an error.

### Five things that must be true, with a test each

```
breach and concern go to both channels
watch goes to slack only
pass goes nowhere
a channel failure is recorded and does not lose the finding or stop the other channel
every dispatch records what was sent, to whom, and which finding ids it came from
the webhook url never appears in a log line or in a DispatchResult
```

The fourth one is the one that matters most. If Slack is down, the email must
still go, the failure must be *recorded*, and the findings must survive. Test it
with a stub channel that raises — the real HTTP call must be wrapped so an
exception becomes a `DispatchResult(delivered=False)`, never a crash.

The sixth is not paranoia. **A Slack webhook URL is a credential** — anyone
holding it can post to our channel. `DispatchResult.detail` gets rendered in the
console, so a URL in there is a URL on a projector.

**Then break each test to prove it works.** Make `dispatch` always send to every
channel and check the `watch goes to slack only` test fails. Let the send
exception propagate and check the failure test fails. Put them back. Thirty
seconds each, and it is the only way to know a test asserts anything —
[`docs/TESTING-LESSONS.md`](../docs/TESTING-LESSONS.md) records a project where
ten of fourteen defects were tests that passed regardless of the code.

### Verify it for real

```sh
set -a && source .env && set +a
curl -s -X POST -H 'Content-type: application/json' \
  --data '{"text":"delivery check"}' "$SLACK_WEBHOOK_URL"
```

Expect `ok` and the message in the channel. **Then read the actual brief when it
sends** — as a transport manager would. It has to name a specific vendor, say
what it was compared against, and be forwardable without editing. If it reads
like a data dump, say so in the channel; the wording is what we are judged on
and it is far cheaper to fix at 11:30 than at 16:30.

---

## Part 2 — the deck and demo script (start by 15:00 at the latest)

**This is the more valuable half of your day.** A polished feature nobody can
follow scores worse than a rough one that is explained well, and the deck is an
explicitly scored deliverable.

### Write the demo script first, before the deck

Eight beats. Time it — you get minutes, not tens of minutes.

1. **"It swept without being asked."** Point at the startup log line.
2. **"Watch it sense."** Start the 60× replay; findings appear live on screen.
3. **"It found this."** The ranked console. Top finding is the worst vendor.
4. **"Here's where the number came from."** Expand the row — references, the rule
   that fired, and the SQL.
5. **"And here's why."** The cause breakdown: which vendors own how many points.
6. **"Here's what it couldn't read, and it says so."** Feed health, the
   quarantined count, a confidence below 0.9 disclosed in the brief itself.
7. **"It sent this."** The Slack message, already in the channel.
8. **"And it will defend it."** Ask it a question; the tool trace is visible.

**Delete any beat whose feature got cut.** A script promising something the build
does not do is worse than a shorter script — and a judge will ask.

### The deck

Short. The four scoring criteria are business impact (35), functionality (25),
agentic design and cost at scale (20), architecture (20) — so:

- **The problem in one slide**, in the statement's own words: *a metric without
  context is just a number.* "OTA is 78%" means nothing; "it was 84.6% last
  month, target is 90%, and two vendors own the gap" is a decision.
- **The loop**: sense → reason → act. Say plainly that it starts on a clock
  tick, not a question — the statement rules out passive dashboards and
  query-only tools, and this is how we clear that bar structurally.
- **The one architectural decision**: the model never computes a number and never
  writes SQL. Rules decide what is wrong; a metric registry answers what the
  figures are; the LLM only writes prose. **Nothing on screen can be a
  hallucinated figure.** This slide is the strongest thing we have — it is also
  the honest answer to "how do we trust it".
- **Cost at scale**: one model call per brief, not one per row, so tokens stay
  flat as the dataset grows. Use the real number off the cost meter. **If the
  rupee figure is not configured, show tokens and say so** — a made-up price is
  the one number a judge can check.
- **Deployability**: it is a stateless service with no backing database, and the
  data layer sits behind one interface, so the same engine reads local files or
  S3. If the AWS deploy happened, show the URL.
- **What we deliberately did not build**, and why. Forecasting, auth,
  multi-tenancy enforcement. Naming your own scope boundaries reads as judgement,
  not as gaps.

### Non-negotiable before presenting

- [ ] **One full rehearsal with the WiFi off.** Beats 1–6 must work completely
      offline. Beats 7 and 8 need the network, so the script must say so, and an
      earlier Slack message must already be in the channel as the fallback.
- [ ] **A screenshot of every beat, in order, in the deck.** If the live demo
      dies you keep going without stopping. This has saved more demos than any
      other single thing.
- [ ] **No credential in any screenshot.** A visible webhook URL has leaked it.
      Check every image, and the terminal scrollback in them.
- [ ] Read `PROPOSAL.md` and §15 of the design spec **tonight**, not at 18:00.
      Somebody has to be holding the narrative, and during the build everyone
      else is heads-down.

### Deliverables checklist

- [ ] Repo pushed, collaborators added
- [ ] Architecture diagram — of **what was built**, not what was planned
- [ ] README with setup instructions someone else can follow
- [ ] Sample inputs and outputs (a fixture excerpt and a real brief)
- [ ] Deck with screenshot fallbacks
- [ ] Demo rehearsed once, offline
- [ ] **Submitted at 17:00** — that window is worth points by itself
