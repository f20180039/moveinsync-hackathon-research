// Pure findings-filter logic for the Insights table (Stage 3) -- parsing
// the Observed math filter and composing every filter with AND. No
// rendering here, so every rule is unit-testable without mounting
// anything.

import type { Finding, Tier } from './types.ts'

export type ObservedTest = (value: number) => boolean

export interface ParsedObservedFilter {
  ok: true
  test: ObservedTest
}

export interface InvalidObservedFilter {
  ok: false
  hint: string
}

const INVALID_HINT = 'Try "< 60", ">= 90", "= 59.1", or "between 40 and 60".'

// Accepts: "< 60", "<= 60", "> 90", ">= 90", "= 59.1", "between 40 and 60"
// (case-insensitive, extra whitespace tolerated). An empty/blank input
// means "no filter" (matches everything) rather than an error -- there's
// nothing to hint about when the field is simply untouched. Anything else
// is invalid: returns a hint, filters nothing (the caller should treat an
// invalid parse as "no filter applied", never as "filter out everything").
export function parseObservedFilter(input: string): ParsedObservedFilter | InvalidObservedFilter {
  const trimmed = input.trim()
  if (trimmed === '') {
    return { ok: true, test: () => true }
  }

  const betweenMatch = /^between\s+(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)$/i.exec(trimmed)
  if (betweenMatch) {
    const a = Number.parseFloat(betweenMatch[1])
    const b = Number.parseFloat(betweenMatch[2])
    const min = Math.min(a, b)
    const max = Math.max(a, b)
    return { ok: true, test: (value) => value >= min && value <= max }
  }

  const comparisonMatch = /^(<=|>=|<|>|=)\s*(-?\d+(?:\.\d+)?)$/.exec(trimmed)
  if (comparisonMatch) {
    const operator = comparisonMatch[1]
    const number = Number.parseFloat(comparisonMatch[2])
    switch (operator) {
      case '<':
        return { ok: true, test: (value) => value < number }
      case '<=':
        return { ok: true, test: (value) => value <= number }
      case '>':
        return { ok: true, test: (value) => value > number }
      case '>=':
        return { ok: true, test: (value) => value >= number }
      case '=':
        return { ok: true, test: (value) => Math.abs(value - number) < 1e-9 }
    }
  }

  return { ok: false, hint: INVALID_HINT }
}

export interface FindingsFilters {
  tiers: Set<Tier>
  metricId: string | null
  dimension: string | null
  observed: ObservedTest | null
}

export const EMPTY_FILTERS: FindingsFilters = {
  tiers: new Set(),
  metricId: null,
  dimension: null,
  observed: null,
}

// The slice-dimension prefix a finding's sliceLabel carries ("vendor",
// "site", ...), or "overall" for the unsliced case. Used both to build the
// dimension select's options and to filter by it.
export function sliceDimensionOf(sliceLabel: string): string {
  if (sliceLabel === 'overall') return 'overall'
  const spaceIndex = sliceLabel.indexOf(' ')
  return spaceIndex === -1 ? sliceLabel : sliceLabel.slice(0, spaceIndex)
}

// Every active filter composes with AND -- a finding must pass all of
// them, not any of them. An empty `tiers` set means "no tier filter" (not
// "match nothing"), matching how an unchecked-everything filter bar reads.
export function applyFindingsFilters(findings: Finding[], filters: FindingsFilters): Finding[] {
  return findings.filter((finding) => {
    if (filters.tiers.size > 0 && !filters.tiers.has(finding.tier)) return false
    if (filters.metricId && finding.metricId !== filters.metricId) return false
    if (filters.dimension && sliceDimensionOf(finding.sliceLabel) !== filters.dimension) return false
    if (filters.observed && !filters.observed(finding.observed)) return false
    return true
  })
}
