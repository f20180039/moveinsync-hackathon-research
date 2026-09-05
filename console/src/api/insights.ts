// Pure derivation logic for the Overview page -- KPI deltas, the priority
// card sentence, which reference "counts" for a metric direction. No
// rendering here, so every rule is unit-testable without mounting anything.

import { formatSliceLabel } from './labels.ts'
import { formatMetricValue, isDataGap } from './types.ts'
import type { Finding, Reference } from './types.ts'

// Metrics where a LOWER observed value is the good direction. Everything
// else defaults to higher-is-better. One place, so a KPI card's delta
// colour and a priority card's framing never disagree with each other.
const LOWER_IS_BETTER_METRICS = new Set(['no_show_rate', 'cost_per_km', 'sev1_alert_rate'])

export function isLowerBetter(metricId: string): boolean {
  return LOWER_IS_BETTER_METRICS.has(metricId)
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
  const improved = value === 0 ? true : isLowerBetter(metricId) ? value < 0 : value > 0
  return {
    value,
    arrow,
    improved,
    magnitude: Math.abs(value).toFixed(1),
    unitWord: unit === '%' ? 'pts' : unit,
  }
}

export function findReference(finding: Pick<Finding, 'references'>, kind: string): Reference | undefined {
  return finding.references.find((ref) => ref.kind === kind)
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
