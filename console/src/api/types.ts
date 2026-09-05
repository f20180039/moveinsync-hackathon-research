// Types for the Signal Desk console API.
//
// Derived directly from `handoff/fake-findings.json`, which is the frozen
// contract for `GET /api/runs/latest/findings`. Field names here must match
// that file exactly -- the service is written against the same fixture.

export type Tier = 'PASS' | 'WATCH' | 'CONCERN' | 'BREACH'

export const TIER_ORDER: readonly Tier[] = ['PASS', 'WATCH', 'CONCERN', 'BREACH']

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
}

export interface FindingsResponse {
  runId: string
  windowLabel: string
  findings: Finding[]
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
}

export interface HealthStatus {
  status: string
  activeMetrics: string[]
  clock: string
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
