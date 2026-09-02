# Deployment & Infrastructure Decision Matrix

**Date:** 2026-09-02 · use this when the problem statement lands and the product
design is drawn, before any service is provisioned.

---

## 1. The default: ONE deployment, zero backing services

`commute-os` as designed (spec v1.1) needs:

| Layer | What | Deployment |
|---|---|---|
| Frontend | Next.js 14 App Router, MapLibre, Tailwind | **1× Vercel project** |
| Backend | Next.js route handlers (`/api/solve`, `/api/explain`, `/api/translate`) | same Vercel project — serverless, no separate service |
| Database | none | — |
| Cache / Redis | none | — |
| Queue / workers | none | — |
| Object storage | none | — |
| Auth | none | — |

**That is the whole deployment.** One `vercel deploy`, or `npm run dev` on the
laptop with the projector.

**Why it needs nothing.** State lives in memory; the world and 200 trips are
committed JSON fixtures; routes come from a precomputed `routes.cache.json`;
both solvers run in milliseconds inside a request. This is design goal G5 —
zero demo-time external dependencies — and it is deliberate, not a gap.

**The reference repos would have you believe otherwise.** `smart-airport` runs
Postgres + Redis + pub/sub + Bun worker threads + Docker Compose for the same
matching problem. That is correct for a production airport service at real
concurrency, and pure liability for a 14-hour demo. Take the algorithm, leave
the infrastructure (`specs/01` §8).

---

## 2. Decision matrix — only if the statement forces it

Each row is a service you did **not** need by default. Read the demo-risk column
before the setup-time column.

| If the statement demands… | You need | Setup | Demo risk | Cheaper alternative |
|---|---|---|---|---|
| Approvals survive a page reload | nothing | 15 min | none | **`localStorage`** — per-viewer, zero infra |
| Approvals shared across viewers | Upstash Redis **or** Vercel KV | 30–45 min | low | one judge's laptop = one viewer; usually unnecessary |
| Real employee roster, thousands of rows | Postgres (Neon/Supabase) + Prisma | 2–3 h | **high** — migrations, connection limits, cold starts | ship a bigger JSON fixture; 200→5,000 trips is a file, not a database |
| Roster CSV upload | nothing | 20 min | none | **`papaparse` in the browser** — parse client-side, never upload |
| Live multi-user dashboard | Pusher / Ably / Supabase Realtime | 1.5–2 h | **high** — websockets over conference wifi | don't. Nobody asks a command centre to be collaborative |
| Sarvam AI (chat / Mayura / Bulbul) | none — env var only | 30 min | **medium** — network on stage | **hard-coded fallback strings** (spec v1.1 §13). Never load-bearing |
| Live routing (Google / ORS) | none — env var only | 30 min | **high** — quota, billing, key | cache-first, always. ORS free tier if you must |
| Auth / roles | NextAuth + provider | 1.5 h | medium | a single admin persona needs no login |
| Scheduled re-solve | Vercel Cron | 30 min | low | solve on demand; it takes 2 ms |
| Driver mobile app | second deployment | ≫ 14 h | — | out of scope, spec §3 |
| 100k+ concurrent match requests | Redis sorted set, worker pool | 3 h+ | **very high** | **not the demo.** A sorted array + binary search is the same complexity at 200 trips (`specs/01` §6) |

### Two rows worth expanding

**Redis is not needed for the corridor index.** `specs/01` shows the H3
prefix-scan implemented on a Redis lexicographic sorted set. At 200 trips an
in-memory sorted array with binary search has identical asymptotics and no
service to start, connect to, or lose on stage. Redis earns its place at
production concurrency — say so if asked, and say why you didn't use it.

**A database is the most tempting wrong turn.** "Real data" feels more
impressive than fixtures, but a Postgres dependency buys you migrations,
connection pooling in serverless, cold starts, and a live schema to debug at
hour 11 — in exchange for something the audience cannot see. Committed
deterministic fixtures are *better* for a demo: identical every run, and
`git diff --exit-code` proves it.

---

## 3. The budget rule

> **Target: 0 extra services. Ceiling: 1. Every added service is a new way for
> the demo to die on stage, and judges score what runs.**

If a statement seems to demand two or more, the design is wrong for a 14-hour
build — cut scope, don't add infrastructure. Cross-check against spec v1.1 §19
Tier C, which already commits to not building most of what would need them.

---

## 4. Checklist to fill in when the design is drawn

Copy this into the design doc and answer every line explicitly:

```
[ ] Frontend deploy target ............. (default: Vercel, 1 project)
[ ] Backend                            . (default: Next.js route handlers, same project)
[ ] Database ........................... (default: NONE — justify any yes)
[ ] Cache / Redis ...................... (default: NONE — justify any yes)
[ ] Realtime / websockets .............. (default: NONE)
[ ] Object storage ..................... (default: NONE)
[ ] Auth ............................... (default: NONE)
[ ] Background jobs / cron ............. (default: NONE)
[ ] External APIs ...................... (Sarvam? routing? each needs a FALLBACK)
[ ] Env vars required .................. (list them; every one must have a default)
[ ] What breaks with NO network? ....... (answer must be: "nothing visible")
[ ] Total services beyond the app ...... (target 0, ceiling 1)
[ ] Offline demo rehearsed end-to-end? . (must be YES before H12 freeze)
```

The line that matters most is **"what breaks with no network?"** If the honest
answer is anything other than *nothing visible*, the architecture is not
demo-safe yet. Conference wifi fails; plan for it as the normal case.

---

## 5. Pre-demo deployment drill

Run this the evening before, not on the day:

```bash
npm run typecheck && npm test          # green
npm run fixtures && git diff --exit-code data/generated/   # deterministic
npm run build && npm start             # production build boots
# then: turn wifi OFF and click through the entire demo script
```

If the offline pass works, no deployment can embarrass you — a laptop and a
projector are a valid production environment.
