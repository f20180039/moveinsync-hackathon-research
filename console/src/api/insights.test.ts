import { describe, expect, it } from 'vitest'
import { buildFindingSentence, computeDelta, isLowerBetter } from './insights.ts'
import type { Finding } from './types.ts'

function makeFinding(overrides: Partial<Finding>): Finding {
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
    audiences: ['TRANSPORT_MANAGER'],
    references: [],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('isLowerBetter', () => {
  it('is true for no_show_rate and cost_per_km', () => {
    expect(isLowerBetter('no_show_rate')).toBe(true)
    expect(isLowerBetter('cost_per_km')).toBe(true)
  })

  it('is false for a higher-is-better metric', () => {
    expect(isLowerBetter('ota')).toBe(false)
  })
})

describe('computeDelta', () => {
  it('marks a rise as an improvement for a higher-is-better metric', () => {
    const delta = computeDelta(92, 88, 'ota', '%')
    expect(delta.arrow).toBe('↑')
    expect(delta.improved).toBe(true)
    expect(delta.magnitude).toBe('4.0')
    expect(delta.unitWord).toBe('pts')
  })

  it('marks a rise as a regression for a lower-is-better metric (colour inverts)', () => {
    const delta = computeDelta(12, 8, 'no_show_rate', '%')
    expect(delta.arrow).toBe('↑')
    expect(delta.improved).toBe(false)
  })

  it('marks a fall as an improvement for a lower-is-better metric', () => {
    const delta = computeDelta(6, 8, 'no_show_rate', '%')
    expect(delta.arrow).toBe('↓')
    expect(delta.improved).toBe(true)
  })

  it('uses the raw unit word for a non-percent metric', () => {
    const delta = computeDelta(21.4, 24.2, 'cost_per_km', 'INR')
    expect(delta.unitWord).toBe('INR')
  })
})

describe('buildFindingSentence', () => {
  it('builds a sentence quoting the peer reference when present', () => {
    const finding = makeFinding({
      metricLabel: 'On-time arrival',
      sliceLabel: 'site San Jose Commons',
      observed: 10.5,
      references: [{ kind: 'PEER', value: 75.8, label: 'peer median' }],
    })

    expect(buildFindingSentence(finding)).toBe(
      'On-time arrival at San Jose Commons is 10.5%, 65.3 points below the peer median of 75.8%.',
    )
  })

  it('omits the "at ..." clause for an overall (unsliced) finding', () => {
    const finding = makeFinding({
      sliceLabel: 'overall',
      observed: 59.1,
      references: [{ kind: 'TARGET', value: 90, label: 'SLA target' }],
    })

    expect(buildFindingSentence(finding)).toBe('On-time arrival is 59.1%, 30.9 points below the SLA target of 90%.')
  })

  it('handles a finding with no references at all', () => {
    const finding = makeFinding({ sliceLabel: 'overall', observed: 59.1, references: [] })

    expect(buildFindingSentence(finding)).toBe('On-time arrival is 59.1%.')
  })

  it('renders a DATA_GAP finding as "could not be measured", not a bare number', () => {
    const finding = makeFinding({
      sliceLabel: 'site Cedar Ridge Office',
      cause: 'DATA_GAP',
      observed: 0,
      references: [],
    })

    expect(buildFindingSentence(finding)).toBe('On-time arrival at Cedar Ridge Office could not be measured this window.')
  })
})
