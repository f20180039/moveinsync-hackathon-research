import { describe, it, expect } from 'vitest'
import { TIER_ORDER, tierRank, worstTier, compareTiers, evaluate, pass, verdict } from '../../src/core/policy'
import type { Candidate, Policy, PolicyCtx, PolicyStatus, World } from '../../src/core/types'

const EMPTY_WORLD = {
  zones: [], offices: [], employees: [], vehicles: [], drivers: [],
  depots: [], metroLines: [], metroStations: [], metroEdges: [],
} as World

const CTX: PolicyCtx = {
  now: 1_757_000_000_000, zoneRejections: {}, trafficMultiplier: 1,
  detourMinutesThisWeek: {},
}

const CAND = {
  tripIds: ['t1'], trips: [], vehicleId: 'v1', driverId: 'd1',
  km: 5, minutes: 15, perPassengerAddedMin: {}, gateIds: ['g1'],
  seatsUsed: 2, pickupTimes: {},
} as Candidate

const mk = (id: string, status: 'pass' | 'soft' | 'medium' | 'block'): Policy => () =>
  status === 'pass'
    ? pass(id, id, 'fine')
    : verdict(id, id, status, 'load', `${id} violated`, { value: -3, unit: 'min' })

describe('tier ordering', () => {
  it('orders pass < soft < medium < block', () => {
    expect(TIER_ORDER).toEqual(['pass', 'soft', 'medium', 'block'])
    expect(tierRank('pass')).toBeLessThan(tierRank('soft'))
    expect(tierRank('soft')).toBeLessThan(tierRank('medium'))
    expect(tierRank('medium')).toBeLessThan(tierRank('block'))
  })

  it('compareTiers sorts worse tiers last', () => {
    expect(compareTiers('pass', 'block')).toBeLessThan(0)
    expect(compareTiers('block', 'soft')).toBeGreaterThan(0)
    expect(compareTiers('soft', 'soft')).toBe(0)
  })

  it('worstTier picks the highest-ranked status', () => {
    expect(worstTier([])).toBe('pass')
    expect(worstTier([pass('a', 'a', 'ok')])).toBe('pass')
    expect(worstTier([
      pass('a', 'a', 'ok'),
      verdict('b', 'b', 'soft', 'unfair_detour', 'meh'),
      verdict('c', 'c', 'medium', 'load', 'bad'),
    ])).toBe('medium')
  })

  it('ranks an unrecognised status WORST, not best (-1 would sort below pass)', () => {
    const bogus = 'corrupted' as PolicyStatus
    expect(tierRank(bogus)).toBeGreaterThan(tierRank('block'))

    // A trace with one bogus verdict must not report tier 'pass' — that would
    // let blocked:true and tier:'pass' coexist on the same PolicyTrace.
    const worst = worstTier([pass('a', 'a', 'ok'), verdict('b', 'b', bogus, 'load', 'bad')])
    expect(worst).not.toBe('pass')
  })
})

describe('evaluate', () => {
  it('runs every policy and returns one verdict each, in order', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'soft')], CAND, EMPTY_WORLD, CTX)
    expect(t.verdicts.map((v) => v.id)).toEqual(['p1', 'p2'])
  })

  it('is not blocked when nothing blocks', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'soft'), mk('p3', 'medium')], CAND, EMPTY_WORLD, CTX)
    expect(t.blocked).toBe(false)
    expect(t.tier).toBe('medium')
  })

  it('is blocked when any policy blocks', () => {
    const t = evaluate([mk('p1', 'pass'), mk('p2', 'block')], CAND, EMPTY_WORLD, CTX)
    expect(t.blocked).toBe(true)
    expect(t.tier).toBe('block')
  })

  it('still evaluates policies AFTER a block — the trace must be complete', () => {
    const t = evaluate([mk('p1', 'block'), mk('p2', 'soft'), mk('p3', 'pass')], CAND, EMPTY_WORLD, CTX)
    expect(t.verdicts.length).toBe(3)
    expect(t.verdicts.map((v) => v.id)).toEqual(['p1', 'p2', 'p3'])
    // The worst verdict is FIRST here, so these two also prove worstTier does a
    // true max scan rather than reading the last element — every other test
    // that checks `tier` happens to put the worst verdict last.
    expect(t.tier).toBe('block')
    expect(t.blocked).toBe(true)
  })

  it('returns an unblocked pass trace for an empty policy list', () => {
    const t = evaluate([], CAND, EMPTY_WORLD, CTX)
    expect(t).toEqual({ verdicts: [], blocked: false, tier: 'pass' })
  })
})

describe('verdict helpers', () => {
  it('pass() produces a pass verdict with no cause', () => {
    const v = pass('x', 'X', 'all good')
    expect(v.status).toBe('pass')
    expect(v.cause).toBeUndefined()
    expect(v.reason).toBe('all good')
  })

  it('verdict() carries cause and slack through', () => {
    const v = verdict('y', 'Y', 'block', 'max_distance', 'too far', { value: -12, unit: 'km' })
    expect(v).toEqual({
      id: 'y', name: 'Y', status: 'block', cause: 'max_distance',
      reason: 'too far', slack: { value: -12, unit: 'km' },
    })
  })
})
