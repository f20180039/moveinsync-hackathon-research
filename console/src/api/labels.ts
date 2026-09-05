// Every raw code/enum value the service sends -- a tier, an audience, a
// reference kind, a cause, a channel, a source, a feed name, a metric id,
// a cost purpose, a slice dimension value -- goes through this module
// before it reaches the screen. Nothing renders SCREAMING_SNAKE_CASE or a
// raw dimension prefix directly. See the "no raw enum text" guard in
// App.test.tsx, which scans every route.

import type { Audience, BriefSource, Tier } from './types.ts'

// Typed against the real union where one exists in types.ts (Tier,
// Audience, BriefSource) -- a new enum member then fails to *compile* here
// instead of silently falling back to humanise() at runtime.

const TIER_LABELS: Record<Tier, string> = {
  PASS: 'Pass',
  WATCH: 'Watch',
  CONCERN: 'Concern',
  BREACH: 'Breach',
}

const AUDIENCE_LABELS: Record<Audience, string> = {
  TRANSPORT_MANAGER: 'Transport manager',
  FACILITIES_HEAD: 'Facilities head',
  LINE_MANAGER: 'Line manager',
}

const SOURCE_LABELS: Record<BriefSource, string> = {
  template: 'Template',
  sarvam: 'Sarvam',
}

// No dedicated union type in types.ts for these (deliberately -- the
// ontology can grow without a type change), so they stay open string maps.

const REFERENCE_KIND_LABELS: Record<string, string> = {
  TREND: '4-week average',
  PEER: 'Peer median',
  TARGET: 'Target',
}

// The rule that fired, in plain English. Moved here (from api/types.ts) so
// every raw-code-to-UI-text mapping lives in one module.
const CAUSE_LABELS: Record<string, string> = {
  TREND_REGRESSION: 'worse than its own recent trend',
  PEER_LAGGARD: 'behind comparable peers',
  LOW_CONFIDENCE: 'too little reliable data to be sure',
  DATA_GAP: 'missing or unmatched data for this slice',
  ON_REFERENCE: 'in line with its reference',
  BELOW_TARGET: 'below its SLA target',
}

const CHANNEL_LABELS: Record<string, string> = {
  slack: 'Slack',
  email: 'Email',
}

const FEED_LABELS: Record<string, string> = {
  trips: 'Trips',
  emp_legs: 'Employee legs',
  feedback: 'Ratings',
  bill: 'Billing',
  alerts: 'Alerts',
}

// Only used as a fallback -- every finding the service sends already
// carries a human `metricLabel`. Kept so a future response missing one
// still renders words, not an id.
const METRIC_LABELS: Record<string, string> = {
  ota: 'On-time arrival',
  otd: 'On-time departure',
  vendor_ota: 'Vendor on-time share',
  no_show_rate: 'No-show rate',
  cost_per_km: 'Cost per km',
  marshal_compliance: 'Marshal compliance (dark hours)',
  sev1_alert_rate: 'Sev-1 alerts per 1,000 trips',
  experience: 'Rider experience',
}

const PURPOSE_LABELS: Record<string, string> = {
  brief: 'Brief',
  ask: 'Ask',
}

// The /decompose dimension selector (VENDOR/SITE/SHIFT/DELAY_REASON, etc.)
// -- same treatment as everything else, never rendered as a raw enum.
const DIMENSION_LABELS: Record<string, string> = {
  VENDOR: 'Vendor',
  SITE: 'Site',
  SHIFT: 'Shift',
  MODE: 'Mode',
  DIRECTION: 'Direction',
  TENANT: 'Business unit',
  DELAY_REASON: 'Delay reason',
}

export type LabelKind =
  | 'tier'
  | 'audience'
  | 'referenceKind'
  | 'cause'
  | 'channel'
  | 'source'
  | 'feed'
  | 'metric'
  | 'purpose'
  | 'dimension'

// Humanises anything not in a map: underscores become spaces, sentence
// case. An unrecognised value from the service still renders as words,
// never as SCREAMING_SNAKE_CASE (or a bare "BUS"/"LOGIN"-style code).
function humanise(value: string): string {
  const words = value.toLowerCase().replace(/_/g, ' ').trim()
  if (!words) return value
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// Looks a value up in a map typed against a specific key set, falling back
// to humanise() for anything the map doesn't cover. The generic keeps each
// call site's map precisely typed (Record<Tier, string>, etc.) without
// forcing every map into one loosely-typed Record<string, string> --
// there's no unsound cast here, `value` genuinely may not be a key of `map`
// (a new/unrecognised value from the service), which is exactly what the
// `??` fallback is for.
function lookup<K extends string>(map: Record<K, string>, value: string): string {
  return (map as Record<string, string>)[value] ?? humanise(value)
}

export function label(kind: LabelKind, value: string): string {
  switch (kind) {
    case 'tier':
      return lookup(TIER_LABELS, value)
    case 'audience':
      return lookup(AUDIENCE_LABELS, value)
    case 'referenceKind':
      return lookup(REFERENCE_KIND_LABELS, value)
    case 'cause':
      return lookup(CAUSE_LABELS, value)
    case 'channel':
      return lookup(CHANNEL_LABELS, value)
    case 'source':
      return lookup(SOURCE_LABELS, value)
    case 'feed':
      return lookup(FEED_LABELS, value)
    case 'metric':
      return lookup(METRIC_LABELS, value)
    case 'purpose':
      return lookup(PURPOSE_LABELS, value)
    case 'dimension':
      return lookup(DIMENSION_LABELS, value)
  }
}

export function causePhrase(cause: string): string {
  return label('cause', cause)
}

// Slice labels are "<dimension> <value>" (or the literal "overall"). Two
// very different kinds of value show up after the dimension prefix:
//   - vendor/site/tenant carry PROPER NOUNS the server made up (a vendor's
//     real name, a site's real name, a business unit code) -- these must
//     render exactly as sent, never reformatted.
//   - mode/direction/shift carry SHORT ENUM CODES ("BUS", "LOGIN", "EARLY")
//     -- these are exactly the kind of raw value this module exists to
//     humanise, so they get their own value maps (with humanise() as the
//     fallback for a code not yet in the map).
const SLICE_DIMENSION_LABELS: Record<string, string> = {
  vendor: 'Vendor',
  site: 'Site',
  tenant: 'Business unit',
  shift: 'Shift',
  mode: 'Mode',
  direction: 'Direction',
}

const ENUM_LIKE_SLICE_DIMENSIONS = new Set(['mode', 'direction', 'shift'])

const SLICE_VALUE_LABELS: Record<string, Record<string, string>> = {
  mode: { BUS: 'Bus', CAB: 'Cab', 'SPOT_2.0': 'Spot 2.0' },
  direction: { LOGIN: 'Login', LOGOUT: 'Logout' },
  shift: { EARLY: 'Early', DAY: 'Day', EVENING: 'Evening', NIGHT: 'Night' },
}

// "vendor Vikram Mikhailov Travel" -> "Vendor: Vikram Mikhailov Travel"
// (proper noun untouched); "mode BUS" -> "Mode: Bus" (enum code
// humanised); "overall" -> "Overall"; a slice label with an unrecognised
// leading word passes through unchanged -- a literal label is still better
// than nothing.
export function formatSliceLabel(raw: string): string {
  if (raw === 'overall') return 'Overall'
  const spaceIndex = raw.indexOf(' ')
  if (spaceIndex === -1) return raw
  const dimension = raw.slice(0, spaceIndex)
  const rest = raw.slice(spaceIndex + 1)
  const dimensionLabel = SLICE_DIMENSION_LABELS[dimension]
  if (!dimensionLabel) return raw

  if (ENUM_LIKE_SLICE_DIMENSIONS.has(dimension)) {
    const value = SLICE_VALUE_LABELS[dimension]?.[rest] ?? humanise(rest)
    return `${dimensionLabel}: ${value}`
  }

  return `${dimensionLabel}: ${rest}`
}
