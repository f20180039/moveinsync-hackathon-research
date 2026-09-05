import { describe, expect, it } from 'vitest'
import { applyFindingsFilters, parseObservedFilter, sliceDimensionOf } from './filters.ts'
import type { Finding } from './types.ts'

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 'f1',
    metricId: 'ota',
    metricLabel: 'On-time arrival',
    unit: '%',
    sliceLabel: 'overall',
    tier: 'BREACH',
    cause: 'BELOW_TARGET',
    observed: 59.1,
    gap: 30.9,
    confidence: 0.96,
    audiences: [],
    references: [],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('parseObservedFilter', () => {
  it.each([
    ['< 60', [59, 60, 61], [true, false, false]],
    ['<= 60', [59, 60, 61], [true, true, false]],
    ['> 90', [89, 90, 91], [false, false, true]],
    ['>= 90', [89, 90, 91], [false, true, true]],
    ['= 59.1', [59.1, 59.2], [true, false]],
    ['between 40 and 60', [39, 40, 50, 60, 61], [false, true, true, true, false]],
    ['between 60 and 40', [50], [true]], // order-independent
  ])('parses "%s" correctly', (input, values, expected) => {
    const result = parseObservedFilter(input)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(values.map((v) => result.test(v))).toEqual(expected)
    }
  })

  it('treats an empty/blank input as "no filter" (matches everything)', () => {
    const result = parseObservedFilter('   ')
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.test(0)).toBe(true)
      expect(result.test(-999)).toBe(true)
    }
  })

  it.each(['banana', '<', '60', '>>90', 'between 40', 'roughly 60'])(
    'rejects invalid input "%s" with a hint, not a thrown error',
    (input) => {
      const result = parseObservedFilter(input)
      expect(result.ok).toBe(false)
      if (!result.ok) {
        expect(result.hint).toMatch(/try/i)
      }
    },
  )
})

describe('sliceDimensionOf', () => {
  it('extracts the dimension prefix', () => {
    expect(sliceDimensionOf('vendor Vikram Mikhailov Travel')).toBe('vendor')
    expect(sliceDimensionOf('site Cedar Ridge Office')).toBe('site')
  })

  it('returns "overall" for the unsliced case', () => {
    expect(sliceDimensionOf('overall')).toBe('overall')
  })
})

describe('applyFindingsFilters', () => {
  const findings: Finding[] = [
    makeFinding({ id: 'a', tier: 'BREACH', metricId: 'ota', sliceLabel: 'overall', observed: 59.1 }),
    makeFinding({ id: 'b', tier: 'CONCERN', metricId: 'otd', sliceLabel: 'site Cedar Ridge Office', observed: 54.7 }),
    makeFinding({ id: 'c', tier: 'PASS', metricId: 'cost_per_km', sliceLabel: 'mode BUS', observed: 21.4 }),
    makeFinding({
      id: 'd',
      tier: 'BREACH',
      metricId: 'vendor_ota',
      sliceLabel: 'vendor Vikram Mikhailov Travel',
      observed: 32.31,
    }),
  ]

  it('filters by tier', () => {
    const result = applyFindingsFilters(findings, {
      tiers: new Set(['BREACH']),
      metricId: null,
      dimension: null,
      observed: null,
    })
    expect(result.map((f) => f.id)).toEqual(['a', 'd'])
  })

  it('filters by metric', () => {
    const result = applyFindingsFilters(findings, {
      tiers: new Set(),
      metricId: 'otd',
      dimension: null,
      observed: null,
    })
    expect(result.map((f) => f.id)).toEqual(['b'])
  })

  it('filters by slice dimension', () => {
    const result = applyFindingsFilters(findings, {
      tiers: new Set(),
      metricId: null,
      dimension: 'vendor',
      observed: null,
    })
    expect(result.map((f) => f.id)).toEqual(['d'])
  })

  it('filters by the observed math filter', () => {
    const parsed = parseObservedFilter('< 55')
    expect(parsed.ok).toBe(true)
    const result = applyFindingsFilters(findings, {
      tiers: new Set(),
      metricId: null,
      dimension: null,
      observed: parsed.ok ? parsed.test : null,
    })
    expect(result.map((f) => f.id)).toEqual(['b', 'c', 'd'])
  })

  it('composes every active filter with AND', () => {
    const parsed = parseObservedFilter('< 60')
    const result = applyFindingsFilters(findings, {
      tiers: new Set(['BREACH']),
      metricId: 'vendor_ota',
      dimension: 'vendor',
      observed: parsed.ok ? parsed.test : null,
    })
    expect(result.map((f) => f.id)).toEqual(['d'])
  })

  it('returns everything when no filter is active', () => {
    const result = applyFindingsFilters(findings, {
      tiers: new Set(),
      metricId: null,
      dimension: null,
      observed: null,
    })
    expect(result).toHaveLength(4)
  })
})
