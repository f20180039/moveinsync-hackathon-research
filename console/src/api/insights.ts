// Pure derivation logic for the Overview page -- KPI deltas, the priority
// card sentence, which reference "counts" for a metric direction. No
// rendering here, so every rule is unit-testable without mounting anything.

import { formatSliceLabel } from './labels.ts'
import { TIER_ORDER, formatMetricValue, isDataGap } from './types.ts'
import type { Finding, Reference } from './types.ts'

// Metrics where a LOWER observed value is the good direction. Everything
// else defaults to higher-is-better. One place, so a KPI card's delta
// colour and a priority card's framing never disagree with each other.
const LOWER_IS_BETTER_METRICS = new Set(['no_show_rate', 'cost_per_km', 'sev1_alert_rate'])

// Task 18: metrics with NO good direction at all -- a demand/volume reading
// where a spike and a collapse are both problems, for opposite reasons (the
// backend's schemas.Metric.better is null for these, and verdict.py judges
// them against constants.BANDS["TWO_SIDED"]). Kept as its own set rather than
// squeezed into the two above, because "lower is better" is exactly the claim
// that is false here: a demand collapse is not an improvement, and colouring
// it green would tell a manager the opposite of what the finding says.
const TWO_SIDED_METRICS = new Set(['riders_per_day'])

export function isLowerBetter(metricId: string): boolean {
  return LOWER_IS_BETTER_METRICS.has(metricId)
}

export function isTwoSided(metricId: string): boolean {
  return TWO_SIDED_METRICS.has(metricId)
}

export interface Delta {
  value: number
  arrow: '↑' | '↓' | '→'
  improved: boolean
  magnitude: string
  unitWord: string
}

// `observed` vs a single reference value (the trend, typically). Direction
// (arrow) is purely arithmetic; `improved` (used for colour) accounts for
// which way is "good" for this metric.
export function computeDelta(observed: number, referenceValue: number, metricId: string, unit: string): Delta {
  const value = observed - referenceValue
  const arrow = value > 0 ? '↑' : value < 0 ? '↓' : '→'
  // For a two-sided metric only being ON the reference is "improved": any
  // move away from it is a finding, whichever way it went.
  const improved = value === 0 ? true
    : isTwoSided(metricId) ? false
    : isLowerBetter(metricId) ? value < 0 : value > 0
  return {
    value,
    arrow,
    improved,
    magnitude: Math.abs(value).toFixed(1),
    unitWord: unit === '%' ? 'pts' : unit,
  }
}

export interface BarDomain {
  min: number
  max: number
}

// The comparison bar's SCALE. It used to be the values' own min and max,
// which made the widget a lie by construction: the smallest value always
// sat hard left and the largest always hard right, so a 0.2-point gap and
// a 40-point gap drew exactly the same picture. Distance carried no
// information at all.
//
// A percentage has a real, universally understood axis, so use it: 0..100.
// Anything else (a cost per km, a rate) has no natural ceiling, so the
// domain is the values' range padded by 60% of the span on each side --
// the markers then sit INSIDE the track, and the space between them is
// proportional to the gap that actually exists.
export function barDomain(values: number[], unit: string): BarDomain {
  if (unit === '%') return { min: 0, max: 100 }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  // Every value identical: give it a symmetric window so the dots land in
  // the middle, stacked, rather than dividing by a zero span.
  if (span === 0) {
    const pad = Math.abs(min) * 0.1 || 1
    return { min: min - pad, max: max + pad }
  }
  const pad = span * 0.6
  return { min: min - pad, max: max + pad }
}

// Where a value sits on that domain, as a percentage of the track. Clamped:
// a reference outside the domain pins to the end rather than escaping the
// track, which is what a value beyond 100% on a percentage axis would do.
export function barPercent(value: number, domain: BarDomain): number {
  const span = domain.max - domain.min || 1
  return Math.min(100, Math.max(0, ((value - domain.min) / span) * 100))
}

export function findReference(finding: Pick<Finding, 'references'>, kind: string): Reference | undefined {
  return finding.references.find((ref) => ref.kind === kind)
}

// The top `limit` findings for a priority-action list, with at most
// `maxPerMetric` per metric id -- so one noisy metric (e.g. 20
// marshal_compliance breaches, one per site) can't fill the whole list on
// its own. Rank order (the input order) is preserved throughout, including
// when a backfill is needed: if the cap leaves fewer than `limit` selected
// (not enough *other* metrics to fill the rest), the remaining slots are
// filled from the capped-out findings -- but the final array is always
// re-sorted by each finding's *original* rank index, not
// selected-then-overflow-appended. Appending would misorder an
// interleaved case: e.g. [m1, m2, m3, m4(marshal), otd1] with limit 4,
// cap 2 selects [m1, m2, otd1] and overflows [m3, m4] -- naively
// appending one overflow slot gives [m1, m2, otd1, m3] (m3, rank 2, lands
// after otd1, rank 4); re-sorting by rank index gives the correct
// [m1, m2, m3, otd1].
export function selectPriorityFindings(findings: Finding[], limit: number, maxPerMetric: number): Finding[] {
  const perMetricCount = new Map<string, number>()
  const selected: { finding: Finding; index: number }[] = []
  const overflow: { finding: Finding; index: number }[] = []

  findings.forEach((finding, index) => {
    const count = perMetricCount.get(finding.metricId) ?? 0
    if (count < maxPerMetric) {
      selected.push({ finding, index })
      perMetricCount.set(finding.metricId, count + 1)
    } else {
      overflow.push({ finding, index })
    }
  })

  if (selected.length >= limit) {
    // Already in rank order by construction (selected only ever grows
    // while walking findings in rank order) -- no backfill, no re-sort
    // needed.
    return selected.slice(0, limit).map((entry) => entry.finding)
  }

  const needed = limit - selected.length
  const chosen = [...selected, ...overflow.slice(0, needed)]
  chosen.sort((a, b) => a.index - b.index)
  return chosen.map((entry) => entry.finding)
}

export interface FindingGroup {
  metricId: string
  metricLabel: string
  findings: Finding[]
}

// Groups findings by metric, preserving the rank order of each metric's
// first appearance -- used by the Alerts page, which (unlike Overview's
// capped top-5) keeps every card but groups them so 20 marshal_compliance
// cards read as one group with a count, not 20 separate top-level cards.
export function groupFindingsByMetric(findings: Finding[]): FindingGroup[] {
  const order: string[] = []
  const groups = new Map<string, Finding[]>()
  for (const finding of findings) {
    if (!groups.has(finding.metricId)) {
      groups.set(finding.metricId, [])
      order.push(finding.metricId)
    }
    groups.get(finding.metricId)!.push(finding)
  }
  return order.map((metricId) => {
    const groupFindings = groups.get(metricId)!
    return { metricId, metricLabel: groupFindings[0].metricLabel, findings: groupFindings }
  })
}

// The unsliced ("overall") finding for one metric, if the sweep produced
// one -- used by every KPI row (Overview, and the weekly/monthly review
// pages). Absent means the metric isn't active at the overall level yet,
// not an error; callers render "Not active yet" (KpiCard already does).
export function findOverall(findings: Finding[], metricId: string): Finding | undefined {
  return findings.find((f) => f.metricId === metricId && f.sliceLabel === 'overall')
}

// The one reference the priority-card sentence quotes -- prefer the peer
// comparison (closest to "is 92% good or bad, compared to whom"), then a
// hard target, then the trend, then whatever's first.
function pickPrimaryReference(references: Reference[]): Reference | undefined {
  return (
    references.find((r) => r.kind === 'PEER') ??
    references.find((r) => r.kind === 'TARGET') ??
    references.find((r) => r.kind === 'TREND') ??
    references[0]
  )
}

// "On-time arrival at San Jose Commons is 10.5%, 65 points below the peer
// median of 75.8%." -- built generically from whichever reference the
// finding actually carries, not hardcoded to one metric.
export function buildFindingSentence(finding: Finding): string {
  if (isDataGap(finding)) {
    const slicePart = sliceForSentence(finding.sliceLabel)
    const subject = slicePart ? `${finding.metricLabel} at ${slicePart}` : finding.metricLabel
    return `${subject} could not be measured this window.`
  }

  const slicePart = sliceForSentence(finding.sliceLabel)
  const subject = slicePart ? `${finding.metricLabel} at ${slicePart}` : finding.metricLabel
  const observedText = formatMetricValue(finding.observed, finding.unit)
  const primaryRef = pickPrimaryReference(finding.references)

  if (!primaryRef) {
    return `${subject} is ${observedText}.`
  }

  const diff = finding.observed - primaryRef.value
  const direction = diff < 0 ? 'below' : diff > 0 ? 'above' : 'level with'
  const magnitude = Math.abs(diff).toFixed(1)
  const unitWord = finding.unit === '%' ? 'points' : finding.unit
  const refText = formatMetricValue(primaryRef.value, finding.unit)
  return `${subject} is ${observedText}, ${magnitude} ${unitWord} ${direction} the ${primaryRef.label} of ${refText}.`
}

// Transport manager's set, and the default for every caller that doesn't
// pass its own (the weekly/monthly review pages, which stay
// role-agnostic) -- unchanged from before role-scoped KPI sets existed.
// Lives here, not in KpiRow.tsx, so roles.ts (a plain data module) can
// reference it without importing a component.
export const DEFAULT_KPI_METRIC_IDS = ['ota', 'otd', 'no_show_rate', 'cost_per_km']

// The floating assistant's default suggested chips. Stage 7's persona
// switch swaps the second chip for the Facilities head role -- kept here
// (a plain data module, not a component) rather than in
// FloatingAssistant.tsx so pulling it into a role-mapping table later
// doesn't need touching the component itself.
// Each one maps onto a tool the interrogator actually has (list_findings /
// explain_finding / decompose_finding / summarize_run), so a starter chip
// never opens with a refusal. "What changed vs last week?" was dropped for
// exactly that reason: there is no cross-window tool, only the TREND
// reference carried on a finding, so it was the one default likely to be
// withheld. Forecast-shaped questions stay off this list for the same
// reason -- a fine demo beat, a bad default.
export const DEFAULT_SUGGESTED_QUESTIONS = [
  'Why is on-time low this week?',
  'Which vendor is worst on on-time?',
  'Where are no-shows concentrated?',
  'Summarise this week',
]

// A finding counts as "recurring" once the same slice has been Concern or
// worse in at least this many of the last `recurrence.of` windows.
// `recurrence` is optional (Task 16, landing on the service partition) --
// feature-detected: no field at all reads as "not recurring", not as a
// crash.
export const RECURRING_THRESHOLD_WEEKS = 3

export function isRecurring(finding: Finding): boolean {
  return (finding.recurrence?.weeks ?? 0) >= RECURRING_THRESHOLD_WEEKS
}

// Stable re-sort: recurring findings float above non-recurring ones, but
// only *within* the same tier -- a CONCERN, recurring or not, never
// outranks a BREACH. Array.prototype.sort is stable in every engine this
// project targets, so findings that tie on both keys keep the server's
// own relative order.
export function sortRecurringFirst(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const tierDiff = TIER_ORDER.indexOf(b.tier) - TIER_ORDER.indexOf(a.tier)
    if (tierDiff !== 0) return tierDiff
    return Number(isRecurring(b)) - Number(isRecurring(a))
  })
}

// "vendor Vikram Mikhailov Travel" -> "Vikram Mikhailov Travel" (drop the
// "Vendor:" framing for a sentence -- "at Vikram Mikhailov Travel" reads
// better than "at Vendor: Vikram Mikhailov Travel"); "overall" -> null (the
// sentence omits the "at ..." clause entirely for the unsliced metric).
export function sliceForSentence(sliceLabel: string): string | null {
  if (sliceLabel === 'overall') return null
  const formatted = formatSliceLabel(sliceLabel)
  const colonIndex = formatted.indexOf(': ')
  return colonIndex === -1 ? formatted : formatted.slice(colonIndex + 2)
}
