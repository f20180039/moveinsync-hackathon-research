import { describe, it, expect } from 'vitest'
import { seatCapacity } from '../../../src/core/policies/seat-capacity'
import { timeWindow, LEAD_TIME_TOLERANCE_MIN } from '../../../src/core/policies/time-window'
import { detourSla, MAX_DETOUR_MIN } from '../../../src/core/policies/detour-sla'
import { gateSpread, MAX_GATES, EXTRA_MIN_PER_GATE } from '../../../src/core/policies/gate-spread'
import { makeWorld, makeCandidate, makeTrip, makeCtx, T0 } from '../../helpers/world'

const W = makeWorld()
const CTX = makeCtx()
const MIN = 60_000

describe('seatCapacity', () => {
  it('passes when seats are available and reports remaining slack', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 3 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 1, unit: 'seats' })
  })

  it('passes when exactly full', () => {
    expect(seatCapacity(makeCandidate({ seatsUsed: 4 }), W, CTX).status).toBe('pass')
  })

  it('blocks when over capacity, with cause=load and negative slack', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 6 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('load')
    expect(v.slack).toEqual({ value: -2, unit: 'seats' })
  })

  it('uses the 12-seat shuttle capacity when the vehicle is a shuttle', () => {
    const v = seatCapacity(makeCandidate({ seatsUsed: 9, vehicleId: 'v-shuttle' }), W, CTX)
    expect(v.status).toBe('pass')
  })

  it('blocks when the vehicle id is unknown — fail closed', () => {
    const v = seatCapacity(makeCandidate({ vehicleId: 'nope' }), W, CTX)
    expect(v.status).toBe('block')
  })
})

describe('timeWindow', () => {
  it('passes when every pickup falls inside a window', () => {
    expect(timeWindow(makeCandidate(), W, CTX).status).toBe('pass')
  })

  it('blocks with cause=delay when a pickup is after the last window end', () => {
    const trip = makeTrip({ windows: [[T0, T0 + 10 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 + 25 * MIN } })
    const v = timeWindow(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('delay')
    expect(v.slack!.value).toBeCloseTo(-15, 6)
  })

  it('satisfies ANY of several windows, not just the first', () => {
    const trip = makeTrip({ windows: [[T0, T0 + 10 * MIN], [T0 + 60 * MIN, T0 + 90 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 + 70 * MIN } })
    expect(timeWindow(c, W, CTX).status).toBe('pass')
  })

  it('flags an excessively early pickup as soft with cause=lead_time', () => {
    const trip = makeTrip({ windows: [[T0 + 60 * MIN, T0 + 90 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 } })
    const v = timeWindow(c, W, CTX)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('lead_time')
  })

  it('tolerates a small early arrival', () => {
    const trip = makeTrip({ windows: [[T0 + 10 * MIN, T0 + 40 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 } })
    expect(timeWindow(c, W, CTX).status).toBe('pass')
    expect(LEAD_TIME_TOLERANCE_MIN).toBe(15)
  })

  it('blocks a pickup in the GAP between two windows', () => {
    // Outside BOTH windows. The old rule only asked "after the latest end?",
    // so a gap pickup fell through to pass() and satisfied no window at all.
    const trip = makeTrip({ windows: [[T0, T0 + 10 * MIN], [T0 + 60 * MIN, T0 + 90 * MIN]] })
    const c = makeCandidate({ trips: [trip], pickupTimes: { t1: T0 + 30 * MIN } })
    const v = timeWindow(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('delay')
    expect(v.slack!.value).toBeCloseTo(-20, 6)   // 20 min past window 1's close
  })
})

describe('detourSla', () => {
  it('passes when nobody is detoured', () => {
    const v = detourSla(makeCandidate(), W, CTX)
    expect(v.status).toBe('pass')
  })

  it('passes a detour inside the 10-minute ceiling', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 8 } })
    expect(detourSla(c, W, CTX).status).toBe('pass')
    expect(MAX_DETOUR_MIN).toBe(10)
  })

  it('blocks a detour beyond the absolute ceiling', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 14 } })
    const v = detourSla(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('delay')
    expect(v.slack!.value).toBeCloseTo(-4, 6)
  })

  it('applies the 30% relative ceiling on a short trip', () => {
    // 20-min trip -> allowance is min(10, 6) = 6 minutes
    const c = makeCandidate({ minutes: 20, perPassengerAddedMin: { e1: 7 } })
    expect(detourSla(c, W, CTX).status).toBe('block')
  })

  it('reports the WORST affected passenger, not the average', () => {
    const c = makeCandidate({ minutes: 60, perPassengerAddedMin: { e1: 1, e2: 14 } })
    const v = detourSla(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toContain('e2')
  })
})

describe('gateSpread', () => {
  it('passes a single gate with no penalty', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1'] }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 0, unit: 'min' })
  })

  it('passes two gates and reports the added minutes', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g2'] }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: -EXTRA_MIN_PER_GATE, unit: 'min' })
  })

  it('blocks three gates with cause=max_tasks', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g2', 'g3'] }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_tasks')
    expect(MAX_GATES).toBe(2)
  })

  it('counts DISTINCT gates only', () => {
    const v = gateSpread(makeCandidate({ gateIds: ['g1', 'g1', 'g1'] }), W, CTX)
    expect(v.status).toBe('pass')
  })
})
