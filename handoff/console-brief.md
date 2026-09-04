# Brief: the manager console (React)

**You own `console/` entirely.** Nobody else will touch it. You do not need the
backend running at any point today — everything you need is in
[`fake-findings.json`](fake-findings.json), which is exactly what the API
returns.

**Paste this file and `fake-findings.json` into your AI agent.** Do not ask it to
explore the repo; it will find Python it should not touch and invent field names.

---

## What this screen is for

A transport manager opens it at 8am. In ten seconds they should know **what went
wrong, how badly, and compared to what.** Not a dashboard of charts they have to
interpret — a ranked list of judgements, each of which can be opened up to show
its own evidence.

The thing that makes this product different from a dashboard is that **every
number can be traced.** Click a row and you see the query that produced it. Build
that path first; it is the demo's best moment.

---

## Setup (should already be done; if not, do this first)

```sh
nvm use                       # Node 22 — Vite 7 fails on 18
cd console && npm install
npm run dev                   # http://localhost:5173
npm test
```

In development, `vite.config.ts` proxies `/api` to `localhost:8080`. Until the
backend exists, import `fake-findings.json` directly instead of fetching.

---

## The data you are rendering

From `fake-findings.json`. TypeScript types — put these in
`src/api/types.ts` and **do not rename anything**:

```ts
export type Tier = 'PASS' | 'WATCH' | 'CONCERN' | 'BREACH'

export interface Reference {
  kind: 'TREND' | 'TARGET' | 'PEER'
  value: number
  label: string          // "4-week average" | "SLA target" | "peer median"
}

export interface Finding {
  id: string
  metricId: string
  metricLabel: string    // "Vendor on-time share" — show this, not metricId
  unit: string           // "%" | "INR" | "score"
  sliceLabel: string     // "vendor V07" | "overall" | "site SITE2"
  tier: Tier
  cause: string          // "PEER_LAGGARD" | "BELOW_TARGET" | ...
  observed: number
  gap: number            // positive ALWAYS means worse
  confidence: number     // 0..1
  audiences: string[]
  references: Reference[]
  evidenceSql: string
  windowLabel?: string
}

export interface FeedHealth {
  feed: string
  rowsLoaded: number
  rowsRejected: number
  unmatchedKeys: number
  nullCriticalFields: number
  confidence: number
  mustBeDisclosed: boolean
}
```

**Four things about this data that are easy to get wrong:**

- **The array is already ranked**, worst first. Never re-sort it. The ordering
  encodes a rule the backend enforces (a `BREACH` outranks any number of
  `WATCH`es — it is deliberately *not* a weighted score) and re-sorting in the UI
  silently throws that away.
- **`gap` is positive when things are worse**, for every metric — including
  `sla_breach` where a higher raw number is bad. You never need to reason about
  the direction; positive is bad. A `PASS` always has a negative gap.
- **`references` can hold one or two entries**, and both must be shown. "78%" is
  a number; "78%, against a target of 90% and a 4-week average of 84.6%" is a
  judgement. Showing only one reference is the single most damaging shortcut
  available in this UI.
- **`confidence` is only shown when below 0.9.** Above that it is noise. Below
  it, it is the product admitting it is unsure — which is a feature, not a
  caveat.

---

## Tier 1 — must be done by 13:00

### 1. `TierBadge`

Severity must be readable **without colour** — a coloured stripe *and* the word.
Two reasons: accessibility, and a projector that washes out red.

```tsx
const STRIPE: Record<Tier, string> = {
  BREACH: '#b3261e', CONCERN: '#a15c00', WATCH: '#5b5bd6', PASS: '#1e7a45',
}

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span aria-hidden style={{ width: 4, height: 16, background: STRIPE[tier], borderRadius: 2 }} />
      <strong style={{ fontSize: 12, letterSpacing: 0.5 }}>{tier}</strong>
    </span>
  )
}
```

### 2. `FindingRow` — collapsed

One row per finding: tier badge, metric label, slice label, the observed value
with its unit, and every reference inline as `label value`. Show
`confidence NN%` in amber **only when `confidence < 0.9`**.

The whole row is a `<button>` with `aria-expanded`, not a `<div>` with an
onClick — keyboard users need it and it costs nothing.

### 3. `EvidencePanel` — expanded

Hidden until the row is clicked. Then a definition list showing: observed value,
**every** reference with its label, the rule that fired (`cause`), the
confidence, who it was sent to (`audiences`), and finally `evidenceSql` in a
`<pre>` with `overflow-x: auto` and `white-space: pre-wrap`.

**The SQL block is the point of this panel.** It is the answer to "where did this
number come from" as something the reader can run, rather than a claim. Make it
readable — monospace, small, scrollable, not truncated.

### 4. `FindingsList`

Maps the array in order. When it is empty, say so plainly — "No findings in this
window." — not an empty div.

### 5. `FeedHealthStrip`

A table over `feedHealth`: feed, rows loaded, **quarantined** (amber when > 0),
unmatched, confidence as a percentage. Mark the row when `mustBeDisclosed`.

The framing that matters: **a row we could not read is a finding, not a log
line.** In the sample data, `feedback` sits at 57% confidence — that is the panel
earning its place, and it is what lets the agent say "I am less sure about the
experience score" instead of quietly reporting a wrong number.

### 6. `App`

Header with the title and a "Sweep now" button. Feed health, then the findings
list. Read from `fake-findings.json` until the backend is up, then
`GET /api/runs/latest/findings`.

---

## Tests — write these first

`npm test` uses Vitest + Testing Library. Each of these must exist and must
actually assert the thing its name claims:

```
renders findings in the order the server ranked them
encodes severity as a text label, not colour alone
shows every reference point for a finding that has two
discloses confidence only when it is below 0.9        ← two cases: 0.62 and 0.97
hides the evidence until asked, then shows the SQL
names the rule that fired alongside the number
says so plainly when a sweep found nothing
shows quarantined rows as a number rather than hiding them
flags a feed whose confidence is below 0.9
```

**Then break each one to prove it works.** Delete the `confidence < 0.9` guard
and check the disclosure test fails. Remove the `<strong>{tier}</strong>` so only
the stripe remains and check the colour-alone test fails. Put them back. This
takes a minute and it is the only way to know a test is asserting anything —
[`docs/TESTING-LESSONS.md`](../docs/TESTING-LESSONS.md) records a project where
**ten of fourteen defects were tests that passed no matter what the code did.**

---

## Tier 2 — only after 13:00, in this order

1. **`CostMeter`** — from `cost` in the sample: calls, tokens per call, and the
   extrapolation to 5,000 employees. **When `pricingConfigured` is false, show
   tokens and say the rupee figure is not configured. Do not invent a price** —
   it is the one number a judge can check.
2. **`BriefPreview`** — render `brief.text` in a `<pre>`, with a "Send this
   brief" button hitting `POST /api/dispatch/{runId}` and showing per-channel
   results. **Do not press send while testing** — it posts to the real Slack
   channel we are demoing.
3. **`ReplayControls`** — start/stop buttons hitting `POST /api/replay/start`
   and `/stop`, showing the simulated date. While running, poll
   `/api/runs/latest/findings` every 2s so **new findings appear on screen as
   the clock advances.** This is the demo's opening beat: *"I'm not going to tell
   you it senses. Watch."* Worth doing well.
4. **`CauseBreakdown`** — a small table in the expanded row from
   `GET /api/findings/{id}/causes`, showing which vendors or delay categories own
   how many points of the gap. Ask before starting this one; the endpoint may not
   exist yet.

---

## Styling

Inline styles are fine. No component library, no Tailwind setup, no design
system — none of it earns its cost in six hours. Plain, dense, legible: system
font, generous line height, a single accent colour per tier. It will be seen on a
projector, so **err large on font sizes and high on contrast.**

Do not build a dark mode. Do not add animations. Do not add a router.

---

## If you finish early

Tell Anshuman rather than adding features. The most valuable thing an idle
person can do after 15:00 is rehearse the demo and take the screenshots that
become the deck's fallback if the live demo dies.
