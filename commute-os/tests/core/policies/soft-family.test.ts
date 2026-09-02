import { describe, it, expect } from 'vitest'
import { zoneConfidence, REJECTION_THRESHOLD } from '../../../src/core/policies/zone-confidence'
import { noShowRisk } from '../../../src/core/policies/no-show-risk'
import { detourFairness, FAIR_WEEKLY_DETOUR_MIN } from '../../../src/core/policies/detour-fairness'
import { ALL_POLICIES } from '../../../src/core/policies/index'
import { evaluate } from '../../../src/core/policy'
import { makeWorld, makeCandidate, makeTrip, makeCtx } from '../../helpers/world'

const W = makeWorld()

describe('zoneConfidence', () => {
  it('passes a zone with no rejection history', () => {
    expect(zoneConfidence(makeCandidate(), W, makeCtx()).status).toBe('pass')
  })

  it('passes below the rejection threshold', () => {
    const ctx = makeCtx({ zoneRejections: { 'z-koramangala': 2 } })
    expect(zoneConfidence(makeCandidate(), W, ctx).status).toBe('pass')
  })

  it('goes soft at the threshold and never blocks', () => {
    const ctx = makeCtx({ zoneRejections: { 'z-koramangala': 5 } })
    const v = zoneConfidence(makeCandidate(), W, ctx)
    expect(v.status).toBe('soft')
    expect(v.reason).toContain('5')
    expect(REJECTION_THRESHOLD).toBe(3)
  })
})

describe('noShowRisk', () => {
  it('never blocks, whatever the risk', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e3'] })] // e3 noShowRate 0.20
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx())
    expect(['pass', 'soft']).toContain(v.status)
  })

  it('flags a high combined no-show probability as soft', () => {
    const trips = [
      makeTrip({ id: 'a', employeeIds: ['e3'] }),  // 0.20
      makeTrip({ id: 'b', employeeIds: ['e2'] }),  // 0.10
    ]
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx())
    expect(v.status).toBe('soft')
    expect(v.slack!.unit).toBe('%')
  })

  it('honours the slider override across all employees', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e4'] })] // 0.02 normally
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx({ noShowOverride: 0.9 }))
    expect(v.status).toBe('soft')
  })

  it('passes a low-risk group', () => {
    const trips = [makeTrip({ id: 'a', employeeIds: ['e4'] })] // 0.02
    expect(noShowRisk(makeCandidate({ trips }), W, makeCtx()).status).toBe('pass')
  })

  it('uses the multiplicative formula, not a sum of rates', () => {
    // Three passengers at 9% each. 1 - 0.91^3 = 0.2464, BELOW the 0.25 threshold
    // => pass. Summing the rates gives 0.27 => soft. This is the only shape that
    // separates the two formulas: every other fixture case puts both on the same
    // side of the threshold, so without this the formula is unpinned and a
    // sum-instead-of-product bug passes the whole suite.
    const trips = [
      makeTrip({ id: 'a', employeeIds: ['e1'] }),
      makeTrip({ id: 'b', employeeIds: ['e2'] }),
      makeTrip({ id: 'c', employeeIds: ['e3'] }),
    ]
    const v = noShowRisk(makeCandidate({ trips }), W, makeCtx({ noShowOverride: 0.09 }))
    expect(v.status).toBe('pass')
    // slack = (0.25 - 0.246429) * 100 — pins the arithmetic, not just the verdict
    expect(v.slack!.value).toBeCloseTo(0.357, 2)
  })
})

describe('detourFairness', () => {
  it('passes when nobody has absorbed much detour', () => {
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 5 } }), W, makeCtx())
    expect(v.status).toBe('pass')
  })

  it('goes soft when an employee exceeds the weekly fair share', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 88 } })
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 6 } }), W, ctx)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('unfair_detour')
    expect(v.reason).toContain('94')
  })

  it('never blocks — fairness is a preference, not a hard rule', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 100_000 } })
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 10 } }), W, ctx).status).toBe('soft')
  })

  it('counts prior load PLUS this candidate, not either alone', () => {
    const ctx = makeCtx({ detourMinutesThisWeek: { e1: 85 } })
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 1 } }), W, ctx).status).toBe('pass')
    expect(detourFairness(makeCandidate({ perPassengerAddedMin: { e1: 10 } }), W, ctx).status).toBe('soft')
  })

  it('includes employees with no prior detour history at zero', () => {
    const v = detourFairness(makeCandidate({ perPassengerAddedMin: { e2: 3 } }), W, makeCtx())
    expect(v.status).toBe('pass')
    expect(FAIR_WEEKLY_DETOUR_MIN).toBe(90)
  })
})

describe('ALL_POLICIES registry', () => {
  it('registers exactly ten policies', () => {
    expect(ALL_POLICIES.length).toBe(10)
  })

  it('produces a complete ten-verdict trace with unique ids', () => {
    const trace = evaluate(ALL_POLICIES, makeCandidate(), W, makeCtx())
    expect(trace.verdicts.length).toBe(10)
    expect(new Set(trace.verdicts.map((v) => v.id)).size).toBe(10)
  })

  it('passes a benign candidate cleanly', () => {
    const trace = evaluate(ALL_POLICIES, makeCandidate(), W, makeCtx())
    expect(trace.blocked).toBe(false)
    expect(trace.tier).toBe('pass')
  })

  it('blocks and still returns all ten verdicts for a bad candidate', () => {
    const bad = makeCandidate({ seatsUsed: 99, gateIds: ['g1', 'g2', 'g3'] })
    const trace = evaluate(ALL_POLICIES, bad, W, makeCtx())
    expect(trace.blocked).toBe(true)
    expect(trace.tier).toBe('block')
    expect(trace.verdicts.length).toBe(10)
  })
})
