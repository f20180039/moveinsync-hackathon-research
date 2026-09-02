import { describe, it, expect } from 'vitest'
import { driverHours, MAX_DUTY_MIN, WARN_DUTY_MIN } from '../../../src/core/policies/driver-hours'
import { evRange, EV_RESERVE_FRACTION } from '../../../src/core/policies/ev-range'
import { genderSafety } from '../../../src/core/policies/gender-safety'
import { makeWorld, makeCandidate, makeTrip, makeCtx } from '../../helpers/world'

const W = makeWorld()
const CTX = makeCtx()

describe('driverHours', () => {
  it('passes a fresh driver and reports remaining minutes', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-fresh', minutes: 30 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 720 - 60 - 30, unit: 'min' })
  })

  it('warns softly as the driver approaches the cap', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-warn', minutes: 20 }), W, CTX)
    expect(v.status).toBe('soft')
    expect(v.cause).toBe('max_travel_time')
  })

  it('blocks when the merge would exceed 12 hours of duty', () => {
    const v = driverHours(makeCandidate({ driverId: 'd-near-cap', minutes: 40 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_travel_time')
    expect(v.slack!.value).toBeCloseTo(-20, 6)
    expect(v.reason).toContain('Suresh')
  })

  it('uses the documented thresholds', () => {
    expect(MAX_DUTY_MIN).toBe(720)
    expect(WARN_DUTY_MIN).toBe(660)
  })

  it('blocks an unknown driver — fail closed', () => {
    expect(driverHours(makeCandidate({ driverId: 'nope' }), W, CTX).status).toBe('block')
  })
})

describe('evRange', () => {
  it('is not applicable to a combustion vehicle', () => {
    const v = evRange(makeCandidate({ vehicleId: 'v-sedan', km: 300 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.reason).toMatch(/not an EV/i)
  })

  it('passes an EV comfortably inside its usable range', () => {
    // 150 km * 100% SoC * 0.8 reserve = 120 km usable
    const v = evRange(makeCandidate({ vehicleId: 'v-ev', km: 80 }), W, CTX)
    expect(v.status).toBe('pass')
    expect(v.slack).toEqual({ value: 40, unit: 'km' })
  })

  it('blocks an EV beyond usable range and names the reassignment', () => {
    const v = evRange(makeCandidate({ vehicleId: 'v-ev', km: 130 }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('max_distance')
    expect(v.reason).toMatch(/CNG|ICE/)
  })

  it('accounts for state of charge, not just nameplate range', () => {
    // v-ev-low: 150 km * 30% * 0.8 = 36 km usable
    expect(evRange(makeCandidate({ vehicleId: 'v-ev-low', km: 30 }), W, CTX).status).toBe('pass')
    expect(evRange(makeCandidate({ vehicleId: 'v-ev-low', km: 50 }), W, CTX).status).toBe('block')
  })

  it('keeps a 20% reserve', () => {
    expect(EV_RESERVE_FRACTION).toBe(0.2)
  })
})

describe('genderSafety', () => {
  const dayTrip = (ids: string[], id = 'td') => makeTrip({ id, employeeIds: ids, isNightShift: false })
  const nightTrip = (ids: string[], id = 'tn') => makeTrip({ id, employeeIds: ids, isNightShift: true })

  it('does not restrict daytime merges at all', () => {
    const c = makeCandidate({ trips: [dayTrip(['e1']), dayTrip(['e3'], 'td2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('blocks a night merge with exactly one female', () => {
    const c = makeCandidate({ trips: [nightTrip(['e1']), nightTrip(['e3'], 'tn2')] })
    const v = genderSafety(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.cause).toBe('skills')
    expect(v.reason).toMatch(/lone female/i)
  })

  it('allows a night merge with two or more females', () => {
    const c = makeCandidate({ trips: [nightTrip(['e1']), nightTrip(['e2'], 'tn2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('allows an all-male night merge', () => {
    const c = makeCandidate({ trips: [nightTrip(['e3']), nightTrip(['e4'], 'tn2')] })
    expect(genderSafety(c, W, CTX).status).toBe('pass')
  })

  it('blocks a lone female as the LAST drop on a night logout', () => {
    // NOTE: two females in the group, so the lone-female rule does NOT fire —
    // this must be caught by the last-drop rule specifically.
    const a = makeTrip({ id: 'l1', employeeIds: ['e1'], isNightShift: true, direction: 'logout' })
    const b = makeTrip({ id: 'l2', employeeIds: ['e3'], isNightShift: true, direction: 'logout' })
    const c = makeTrip({ id: 'l3', employeeIds: ['e2'], isNightShift: true, direction: 'logout' })
    const v = genderSafety(makeCandidate({ trips: [a, b, c] }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toMatch(/last drop/i)
    expect(v.reason).toContain('Bhavna')
  })

  it('allows a male last drop on a night logout', () => {
    const a = makeTrip({ id: 'l1', employeeIds: ['e1'], isNightShift: true, direction: 'logout' })
    const b = makeTrip({ id: 'l2', employeeIds: ['e2'], isNightShift: true, direction: 'logout' })
    const c = makeTrip({ id: 'l3', employeeIds: ['e3'], isNightShift: true, direction: 'logout' })
    expect(genderSafety(makeCandidate({ trips: [a, b, c] }), W, CTX).status).toBe('pass')
  })

  it('evaluates the resolvable passengers when one employee id is unresolvable', () => {
    // 'ghost' cannot be resolved, but e3 (male) still resolves — this should
    // evaluate normally on the resolvable passengers, not blanket-pass or throw.
    const c = makeCandidate({ trips: [nightTrip(['ghost']), nightTrip(['e3'], 'tn2')] })
    const v = genderSafety(c, W, CTX)
    expect(() => genderSafety(c, W, CTX)).not.toThrow()
    expect(v.status).toBe('pass')
  })

  it('blocks a night merge where NO employee id resolves — fail closed', () => {
    const c = makeCandidate({ trips: [nightTrip(['ghost1']), nightTrip(['ghost2'], 'tn2')] })
    const v = genderSafety(c, W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toMatch(/cannot resolve/i)
  })

  it('does not let a DAY-leg female shield a lone female on the night leg', () => {
    const nightLoneF = makeTrip({ id: 'n1', employeeIds: ['e1'], isNightShift: true })
    const dayOtherF = makeTrip({ id: 'd1', employeeIds: ['e2'], isNightShift: false })
    const v = genderSafety(makeCandidate({ trips: [nightLoneF, dayOtherF] }), W, CTX)
    expect(v.status).toBe('block')
    expect(v.reason).toMatch(/lone female/i)
  })
})
