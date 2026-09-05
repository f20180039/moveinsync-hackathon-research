// Every raw code/enum value the service sends -- a tier, an audience, a
// reference kind, a cause, a channel, a source, a feed name, a metric id,
// a cost purpose -- goes through this module before it reaches the screen.
// Nothing renders SCREAMING_SNAKE_CASE or a raw dimension prefix directly.
// See the "no raw enum text" guard in App.test.tsx.

const TIER_LABELS: Record<string, string> = {
  PASS: 'Pass',
  WATCH: 'Watch',
  CONCERN: 'Concern',
  BREACH: 'Breach',
}

const AUDIENCE_LABELS: Record<string, string> = {
  TRANSPORT_MANAGER: 'Transport manager',
  FACILITIES_HEAD: 'Facilities head',
  LINE_MANAGER: 'Line manager',
}

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

const SOURCE_LABELS: Record<string, string> = {
  template: 'Template',
  sarvam: 'Sarvam',
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

const MAPS: Record<LabelKind, Record<string, string>> = {
  tier: TIER_LABELS,
  audience: AUDIENCE_LABELS,
  referenceKind: REFERENCE_KIND_LABELS,
  cause: CAUSE_LABELS,
  channel: CHANNEL_LABELS,
  source: SOURCE_LABELS,
  feed: FEED_LABELS,
  metric: METRIC_LABELS,
  purpose: PURPOSE_LABELS,
}

// Humanises anything not in a map: underscores become spaces, sentence
// case. An unrecognised value from the service still renders as words,
// never as SCREAMING_SNAKE_CASE.
function humanise(value: string): string {
  const words = value.toLowerCase().replace(/_/g, ' ').trim()
  if (!words) return value
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function label(kind: LabelKind, value: string): string {
  return MAPS[kind][value] ?? humanise(value)
}

export function causePhrase(cause: string): string {
  return label('cause', cause)
}

const SLICE_DIMENSION_LABELS: Record<string, string> = {
  vendor: 'Vendor',
  site: 'Site',
  tenant: 'Business unit',
  shift: 'Shift',
  mode: 'Mode',
  direction: 'Direction',
}

// "vendor Vikram Mikhailov Travel" -> "Vendor: Vikram Mikhailov Travel";
// "overall" -> "Overall"; a slice label with an unrecognised leading word
// passes through unchanged -- a literal label is still better than nothing.
export function formatSliceLabel(raw: string): string {
  if (raw === 'overall') return 'Overall'
  const spaceIndex = raw.indexOf(' ')
  if (spaceIndex === -1) return raw
  const dimension = raw.slice(0, spaceIndex)
  const rest = raw.slice(spaceIndex + 1)
  const dimensionLabel = SLICE_DIMENSION_LABELS[dimension]
  return dimensionLabel ? `${dimensionLabel}: ${rest}` : raw
}
