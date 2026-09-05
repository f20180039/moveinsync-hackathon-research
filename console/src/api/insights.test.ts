import { describe, expect, it } from 'vitest'
import { buildFindingSentence, computeDelta, groupFindingsByMetric, isLowerBetter, selectPriorityFindings } from './insights.ts'
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

describe('selectPriorityFindings', () => {
  function makeMany(metricId: string, count: number, startId = 0): Finding[] {
    return Array.from({ length: count }, (_, i) =>
      makeFinding({ id: `${metricId}-${startId + i}`, metricId, sliceLabel: `site Site ${startId + i}` }),
    )
  }

  it('caps a noisy metric at 2 cards, filling the rest of the top 5 from other metrics (20 marshal breaches + 3 others -> 2 + 3)', () => {
    const findings = [...makeMany('marshal_compliance', 20), ...makeMany('otd', 1), ...makeMany('sev1_alert_rate', 1), ...makeMany('no_show_rate', 1)]

    const result = selectPriorityFindings(findings, 5, 2)

    expect(result).toHaveLength(5)
    const byMetric = new Map<string, number>()
    for (const f of result) byMetric.set(f.metricId, (byMetric.get(f.metricId) ?? 0) + 1)
    expect(byMetric.get('marshal_compliance')).toBe(2)
    expect(byMetric.get('otd')).toBe(1)
    expect(byMetric.get('sev1_alert_rate')).toBe(1)
    expect(byMetric.get('no_show_rate')).toBe(1)
  })

  it('preserves rank order among the selected findings', () => {
    const findings = [
      makeFinding({ id: 'a', metricId: 'ota' }),
      makeFinding({ id: 'b', metricId: 'otd' }),
      makeFinding({ id: 'c', metricId: 'ota' }),
    ]
    const result = selectPriorityFindings(findings, 5, 2)
    expect(result.map((f) => f.id)).toEqual(['a', 'b', 'c'])
  })

  it('fills remaining slots from the capped-out overflow when there are not enough other metrics', () => {
    // Only one metric present at all -- the cap alone would yield 2, but
    // there are 5 findings and a limit of 5, so overflow fills the rest.
    const findings = makeMany('marshal_compliance', 5)
    const result = selectPriorityFindings(findings, 5, 2)
    expect(result).toHaveLength(5)
  })
})

describe('groupFindingsByMetric', () => {
  it('groups by metric, preserving each group\'s first-appearance rank order', () => {
    const findings: Finding[] = [
      makeFinding({ id: 'a', metricId: 'marshal_compliance', metricLabel: 'Marshal compliance (dark hours)' }),
      makeFinding({ id: 'b', metricId: 'otd', metricLabel: 'On-time departure' }),
      makeFinding({ id: 'c', metricId: 'marshal_compliance', metricLabel: 'Marshal compliance (dark hours)' }),
    ]

    const groups = groupFindingsByMetric(findings)

    expect(groups.map((g) => g.metricId)).toEqual(['marshal_compliance', 'otd'])
    expect(groups[0].findings.map((f) => f.id)).toEqual(['a', 'c'])
    expect(groups[0].metricLabel).toBe('Marshal compliance (dark hours)')
    expect(groups[1].findings.map((f) => f.id)).toEqual(['b'])
  })
})
