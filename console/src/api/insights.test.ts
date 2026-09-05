import { describe, expect, it } from 'vitest'
import {
  barDomain,
  barPercent,
  buildFindingSentence,
  computeDelta,
  groupFindingsByMetric,
  isLowerBetter,
  isRecurring,
  selectPriorityFindings,
  sortRecurringFirst,
} from './insights.ts'
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

  it('interleaves the overflow backfill by original rank, not appended after every selected finding', () => {
    // [m1, m2, m3, m4(marshal), otd1], limit 4, cap 2 -- m1/m2 selected,
    // m3/m4 overflow (cap reached), otd1 selected. Only 1 backfill slot is
    // needed (selected has 3, limit is 4) -- naively appending it after
    // the selected findings would put m3 (rank 2) after otd1 (rank 4),
    // which is wrong: m3 outranks otd1 and must come first.
    const findings = [
      makeFinding({ id: 'm1', metricId: 'marshal_compliance' }),
      makeFinding({ id: 'm2', metricId: 'marshal_compliance' }),
      makeFinding({ id: 'm3', metricId: 'marshal_compliance' }),
      makeFinding({ id: 'm4', metricId: 'marshal_compliance' }),
      makeFinding({ id: 'otd1', metricId: 'otd' }),
    ]

    const result = selectPriorityFindings(findings, 4, 2)

    expect(result.map((f) => f.id)).toEqual(['m1', 'm2', 'm3', 'otd1'])
  })

  it('fills remaining slots from the capped-out overflow when there are not enough other metrics', () => {
    // Only one metric present at all -- the cap alone would yield 2, but
    // there are 5 findings and a limit of 5, so overflow fills the rest.
    const findings = makeMany('marshal_compliance', 5)
    const result = selectPriorityFindings(findings, 5, 2)
    expect(result).toHaveLength(5)
  })
})

describe('isRecurring', () => {
  it('is true at 3 of the last 4 weeks and at 4 of 4', () => {
    expect(isRecurring(makeFinding({ recurrence: { weeks: 3, of: 4 } }))).toBe(true)
    expect(isRecurring(makeFinding({ recurrence: { weeks: 4, of: 4 } }))).toBe(true)
  })

  it('is false at 2 of the last 4 weeks', () => {
    expect(isRecurring(makeFinding({ recurrence: { weeks: 2, of: 4 } }))).toBe(false)
  })

  it('is false when recurrence is absent (feature-detected, not a crash)', () => {
    expect(isRecurring(makeFinding({}))).toBe(false)
  })
})

describe('sortRecurringFirst', () => {
  it('floats a recurring finding above a non-recurring one within the same tier', () => {
    const findings = [
      makeFinding({ id: 'a', tier: 'BREACH' }),
      makeFinding({ id: 'b', tier: 'BREACH', recurrence: { weeks: 3, of: 4 } }),
      makeFinding({ id: 'c', tier: 'BREACH' }),
    ]

    expect(sortRecurringFirst(findings).map((f) => f.id)).toEqual(['b', 'a', 'c'])
  })

  it('never lets a recurring CONCERN outrank a non-recurring BREACH', () => {
    const findings = [
      makeFinding({ id: 'concern-recurring', tier: 'CONCERN', recurrence: { weeks: 4, of: 4 } }),
      makeFinding({ id: 'breach-plain', tier: 'BREACH' }),
    ]

    expect(sortRecurringFirst(findings).map((f) => f.id)).toEqual(['breach-plain', 'concern-recurring'])
  })

  it('keeps the server\'s relative order among findings that tie on tier and recurrence', () => {
    const findings = [
      makeFinding({ id: 'a', tier: 'BREACH' }),
      makeFinding({ id: 'b', tier: 'BREACH' }),
      makeFinding({ id: 'c', tier: 'BREACH' }),
    ]

    expect(sortRecurringFirst(findings).map((f) => f.id)).toEqual(['a', 'b', 'c'])
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

// The comparison bar's scale. See barDomain's own comment for why the
// previous min/max-of-its-own-values version drew every gap identically.
describe('barDomain / barPercent', () => {
  it('uses the real 0..100 axis for a percentage, not the values own range', () => {
    expect(barDomain([78, 84.6], '%')).toEqual({ min: 0, max: 100 })
  })

  it('draws a small gap small and a large gap large', () => {
    const domain = barDomain([78, 84.6], '%')
    const smallGap = barPercent(84.6, domain) - barPercent(78, domain)

    const wideDomain = barDomain([40, 90], '%')
    const largeGap = barPercent(90, wideDomain) - barPercent(40, wideDomain)

    expect(largeGap).toBeGreaterThan(smallGap * 5)
  })

  it('keeps every marker inside the track for a unit with no natural ceiling', () => {
    const values = [24.5, 31.2]
    const domain = barDomain(values, 'INR/km')

    for (const v of values) {
      expect(barPercent(v, domain)).toBeGreaterThan(0)
      expect(barPercent(v, domain)).toBeLessThan(100)
    }
  })

  it('centres identical values instead of dividing by a zero span', () => {
    const domain = barDomain([12, 12], 'INR')
    expect(barPercent(12, domain)).toBeCloseTo(50)
  })

  it('clamps a value beyond the axis to the end of the track', () => {
    const domain = barDomain([50], '%')
    expect(barPercent(140, domain)).toBe(100)
    expect(barPercent(-10, domain)).toBe(0)
  })
})
