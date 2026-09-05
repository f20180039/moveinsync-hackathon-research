// Types for the Signal Desk console API.
//
// Derived directly from `handoff/fake-findings.json`, which is the frozen
// contract for `GET /api/runs/latest/findings`. Field names here must match
// that file exactly -- the service is written against the same fixture.

export type Tier = 'PASS' | 'WATCH' | 'CONCERN' | 'BREACH'

export const TIER_ORDER: readonly Tier[] = ['PASS', 'WATCH', 'CONCERN', 'BREACH']

// "Needs attention" -- CONCERN or BREACH. The one place this threshold is
// defined; the sidebar's unread-alert badge count and the Alerts page's
// filter both call this instead of repeating the `=== 'CONCERN' || ===
// 'BREACH'` check.
export function isAlertTier(tier: Tier): boolean {
  return tier === 'CONCERN' || tier === 'BREACH'
}

// The live causes today are TREND_REGRESSION, PEER_LAGGARD, LOW_CONFIDENCE,
// DATA_GAP, ON_REFERENCE and BELOW_TARGET. Kept as `string` (rather than a
// union) so an unrecognised cause from the service still renders instead of
// failing to type-check -- the phrase map below falls back to the raw code.
export type Cause = string

// Reference kinds render generically: whatever `kind`/`label`/`value` the
// service sends is shown as-is. TREND and PEER exist today; TARGET may
// arrive later. No switch on `kind` anywhere in the UI.
export interface Reference {
  kind: string
  value: number
  label: string
}

// The top 2 contributors to a CONCERN/BREACH finding's shortfall, computed
// server-side so the console never has to fetch /decompose just to fill in
// the "Why" column. `value` is already the display name (a vendor, a site,
// whatever the service picked) -- there is no separate `label` here the way
// DecomposeRow has one.
export interface OwnsRow {
  value: string
  pointsOfGap: number
  n: number
}

export interface Finding {
  id: string
  metricId: string
  metricLabel: string
  unit: string
  sliceLabel: string
  tier: Tier
  cause: Cause
  observed: number
  gap: number
  confidence: number
  audiences: string[]
  references: Reference[]
  evidenceSql: string
  windowLabel?: string
  // Landing on the service partition -- optional until every deployed
  // service has it. "" for PASS.
  action?: string
  // Landing alongside `action` -- present (non-empty) on CONCERN/BREACH
  // findings, empty on PASS/WATCH. Feature-detect: absent or empty means
  // "no server-computed contributors yet", not an error -- the Why column
  // falls back to the cause phrase.
  owns?: OwnsRow[]
  // Landing on the service partition (Task 16) -- optional, present only
  // on CONCERN/BREACH findings: how many of the last `of` windows this
  // same slice was also Concern or worse. Feature-detect: absent means
  // "not computed for this finding", not zero.
  recurrence?: Recurrence
}

export interface Recurrence {
  weeks: number
  of: number
}

export interface FindingsResponse {
  runId: string
  windowLabel: string
  findings: Finding[]
  // Landing shortly -- present once the service supports week/month sweeps.
  windowDays?: number
  windowKind?: 'week' | 'month'
}

export type SweepWindow = 'week' | 'month'

// GET /api/findings/{id}/decompose?dim=... -- one row per contributor
// (a vendor, a site, a delay reason, ...) to a finding's shortfall.
export interface DecomposeRow {
  value: string
  label: string
  observed: number
  shareOfVolume: number
  pointsOfGap: number
  n: number
}

export type DecomposeDimension = 'VENDOR' | 'SITE' | 'SHIFT' | 'MODE' | 'DIRECTION' | 'TENANT' | 'DELAY_REASON'

export interface DecomposeResponse {
  findingId: string
  dim: DecomposeDimension
  overallObserved: number
  gap: number
  rows: DecomposeRow[]
}

// POST /api/ask -- not live yet; every caller must feature-detect (404 ->
// hide/disable) rather than assume this exists.
export interface AskRequest {
  runId: string
  question: string
}

// One tool call the assistant made while answering -- rendered verbatim in
// the collapsible trace, never summarised or reworded.
export interface AskTraceStep {
  tool: string
  arguments: Record<string, unknown>
  result: unknown
}

export interface AskResponse {
  runId: string
  question: string
  // null exactly when `withheld` is true -- the refusal case. Never treat
  // a null answer as an error: render `reason` and the trace instead.
  answer: string | null
  withheld: boolean
  reason: string | null
  trace: AskTraceStep[]
}

// A named, quantified pattern the sweep noticed and handled in this feed
// (e.g. "slab-billed lines with no distance") -- the demo beat is "here is
// what the data does that we noticed and handled," not a hidden data-
// quality issue.
export interface FeedQuirk {
  name: string
  rows: number
  detail: string
}

export interface FeedHealth {
  feed: string
  rowsLoaded: number
  rowsRejected: number
  unmatchedKeys: number
  nullCriticalFields: number
  confidence: number
  mustBeDisclosed: boolean
  // Landing on the service partition -- optional, feature-detect: absent
  // means nothing to show, not an error.
  quirks?: FeedQuirk[]
}

export type Audience = 'TRANSPORT_MANAGER' | 'FACILITIES_HEAD' | 'LINE_MANAGER'

export const AUDIENCES: readonly Audience[] = [
  'TRANSPORT_MANAGER',
  'FACILITIES_HEAD',
  'LINE_MANAGER',
]

export type BriefSource = 'sarvam' | 'template'

export interface Brief {
  runId: string
  audience: Audience
  brief: string
  source: BriefSource
}

export interface DispatchChannelResult {
  channel: string
  delivered: boolean
  detail: string
}

export interface DispatchAudienceResult {
  audience: string
  tier: Tier
  channels: DispatchChannelResult[]
  findingIds: string[]
}

export interface DispatchResponse {
  runId: string
  dispatched: DispatchAudienceResult[]
}

// Landing on the service partition -- shape is a best-effort inference
// from the coordinator's prose example ("MoveInSync raised Woman
// travelling alone on 412 trips this week; an escort was present on 6%"),
// not a confirmed JSON schema yet. Feature-detect: absent/404 means no
// banner, not an error.
export interface SafetySummary {
  metric: string
  trips: number
  escortPresentPct: number
}

export interface LatencyStat {
  n: number
  p50Ms: number
  p95Ms: number
  maxMs: number
}

export interface Cost {
  calls: number
  inputTokens: number
  outputTokens: number
  tokensPerCall: number
  inr: number
  inrPerOrgPerMonth: number
  employeesAtScale: number
  inrPerEmployeePerMonth: number
  byPurpose: Record<string, number>
  pricingConfigured: boolean
  rateIsApproximate: boolean
  // Measured, per label ("metric_query", "sweep", "model_call", "ask_call").
  // A label the service never exercised is ABSENT, not zero -- optional here
  // for the same reason, so a build that predates the meter renders without
  // inventing a latency of nothing.
  latency?: Record<string, LatencyStat>
}

export interface HealthStatus {
  status: string
  activeMetrics: string[]
  clock: string
  // The optional endpoints this build actually serves ("ask", "decompose",
  // "safety", "employees", "cost", "dispatch-log"). Optional on purpose:
  // a service that predates the field omits it, and absence must be read
  // as "unknown, assume available" -- see hasCapability in client.ts.
  capabilities?: string[]
}

export interface SweepResult {
  runId: string
  findingCount: number
}

// The rule-that-fired -> plain-English phrase map, and every other raw
// code/enum -> UI text mapping, lives in `./labels.ts` (`causePhrase`,
// `label`, `formatSliceLabel`) -- one module, so nothing in the UI ever
// renders SCREAMING_SNAKE_CASE.

// Confidence is noise above this line and a feature below it -- the product
// admitting it is unsure. Shared threshold: everywhere confidence is
// disclosed at all (a finding row, a feed health cell) uses this same test.
export const CONFIDENCE_DISCLOSURE_THRESHOLD = 0.9

export function shouldDiscloseConfidence(confidence: number): boolean {
  return confidence < CONFIDENCE_DISCLOSURE_THRESHOLD
}

// A feed is flagged when confidence is low OR the server says so directly
// via `mustBeDisclosed` -- ORed so a server-side disclosure reason (e.g. a
// data-quality issue that doesn't show up as low confidence) can never be
// silently hidden just because the confidence number alone looks fine.
export function shouldFlagFeed(feed: Pick<FeedHealth, 'confidence' | 'mustBeDisclosed'>): boolean {
  return shouldDiscloseConfidence(feed.confidence) || feed.mustBeDisclosed
}

// "%" reads fine glued to the number ("59.1%"); every other unit
// ("score", "INR", "per 1k") needs a space ("3.42 score"). One place, so
// every value -- observed or a reference -- renders the same way.
export function formatMetricValue(value: number, unit: string): string {
  return unit === '%' ? `${value}${unit}` : `${value} ${unit}`
}

// A DATA_GAP finding arrives with observed: 0.0 and no references -- that
// zero is not a measurement, it's the absence of one. Rendering "0%" would
// read as a real (and alarming) number; every cell that would otherwise
// show that bare zero renders "—" (an em dash) or "could not be
// measured" instead, so no cell is ever an uncontextualised number.
export function isDataGap(finding: Pick<Finding, 'cause'>): boolean {
  return finding.cause === 'DATA_GAP'
}

export const NOT_MEASURED = '—'
export const NOT_MEASURED_EXPLANATION = 'could not be measured'

// GET /api/employees/impact -- field names taken verbatim from
// service/signaldesk/api.py's get_employees_impact(). Every number here is
// served; the console renders them and derives none of them.
//
// Two different delay readings live on this response and are deliberately
// labelled apart: latePickupLegs/avgPickupDelayMin/medianPickupDelayMin are
// delay an employee EXPERIENCES, employeeCausedDelayShare is delay
// employees CAUSE.
export interface EmployeeImpactCounts {
  legs: number
  noShows: number
  latePickups: number
  impacted: number
}

export interface EmployeeImpactShiftRow extends EmployeeImpactCounts {
  shiftBand: string
}

export interface EmployeeImpactSiteRow extends EmployeeImpactCounts {
  site: string
}

export interface EmployeeImpactVendorRow extends EmployeeImpactCounts {
  vendor: string
}

export interface EmployeeImpact {
  runId: string
  window: { start: number; end: number; label: string }
  employeesImpacted: number
  ridersInWindow: number
  noShowLegs: number
  latePickupLegs: number
  // Nullable on the service side (`_round` passes None straight through)
  // whenever the window has nothing to measure -- rendered as NOT_MEASURED,
  // never as a zero that would read as a real measurement.
  avgPickupDelayMin: number | null
  medianPickupDelayMin: number | null
  employeeCausedDelayShare: number | null
  byShiftBand: EmployeeImpactShiftRow[]
  bySite: EmployeeImpactSiteRow[]
  byVendor: EmployeeImpactVendorRow[]
  costPerRider: number | null
  costPerRiderTrend: number | null
}


// GET /api/outlook/shifts -- field names verbatim from
// service/signaldesk/forecast.py's Projection.to_json(). This is a STATED
// SEASONAL BASELINE, not a prediction: each projection is the
// recency-weighted mean of the same weekday over the last four weeks, and
// carries the basis observations that produced it.
export interface OutlookBasis {
  date: string
  weekday: string
  weeksBack: number
  weight: number
  value: number | null
  windowStartMs: number
  windowEndMs: number
  sql: string
}

export interface OutlookProjection {
  metric: string
  metricLabel: string
  unit: string
  slice: string
  targetDate: string
  targetStartMs: number
  // null whenever `withheld` -- too few basis days to state a number. That
  // is a refusal, not a zero, and must never render as one.
  projected: number | null
  intervalLow: number | null
  intervalHigh: number | null
  readiness: string
  tier: Tier | null
  reference: { kind: string; label: string; value: number } | null
  action: string
  method: string
  basisDaysUsed: number
  degraded: boolean
  withheld: boolean
  note: string
  basis: OutlookBasis[]
}

export interface ShiftOutlook {
  runId: string
  metric: string
  method: string
  basisWeeks: number
  weights: number[]
  targetDate: string | null
  targetStartMs: number
  shifts: OutlookProjection[]
}
