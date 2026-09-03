import { describe, it, expect } from 'vitest'
import { buildCandidate, soloMinutes } from '../../src/solvers/candidate'
import { createRouteProvider, type RouteProvider } from '../../src/core/routing'
import { boardingMinutes } from '../../src/core/ledger'
import { makeWorld, makeTrip } from '../helpers/world'
import type { LatLng } from '../../src/core/types'

const W = makeWorld()
const RP = createRouteProvider({}) // estimate tier only — deterministic

/**
 * A directional route stub: `a -> b` costs `forwardMin`, `b -> a` costs
 * `backwardMin`. The default estimate-tier RP is symmetric (haversine is
 * commutative), so a soloMinutes/buildCandidate bug that silently always
 * routes home -> gate is INVISIBLE against `RP` — this is the only way to
 * exercise the direction-correct routing path at all.
 */
function directionalRP(from: LatLng, to: LatLng, forwardMin: number, backwardMin: number): RouteProvider {
  return {
    route(a: LatLng, b: LatLng) {
      const forward = a.lat === from.lat && a.lng === from.lng && b.lat === to.lat && b.lng === to.lng
      const minutes = forward ? forwardMin : backwardMin
      return { km: minutes, minutes, polyline: [a, b], source: 'estimate' }
    },
  }
}

describe('buildCandidate', () => {
  it('case 1: single trip — km equals the solo route km, perPassengerAddedMin is exactly 0', () => {
    const trip = makeTrip()
    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, RP)
    const gate = W.offices[0]!.gates[0]!
    const solo = RP.route(trip.pickupAt, gate.at)
    expect(c.km).toBeCloseTo(solo.km, 9)
    expect(c.minutes).toBeCloseTo(soloMinutes(trip, W, RP), 9)
    expect(c.perPassengerAddedMin['e1']).toBe(0)
  })

  it('case 2: two trips at the same gate collapse to one distinct gate', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], gateId: 'g1' })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], gateId: 'g1',
      pickupAt: { lat: 12.940, lng: 77.630 },
    })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    expect(c.gateIds).toEqual(['g1'])
  })

  it('case 3: two trips at different gates — distinct gates, in visit order', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], gateId: 'g2' })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], gateId: 'g1',
      pickupAt: { lat: 12.940, lng: 77.630 },
    })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    expect(c.gateIds).toEqual(['g2', 'g1']) // a's gate visited first, b's second
  })

  it('case 4: boarding minutes are split ONCE across stops/passengers, not per trip', () => {
    // Same pickupAt on purpose: this collapses to ONE distinct stop with 2
    // passengers. boardingMinutes is linear in stops and pax SEPARATELY, so a
    // two-different-locations case can't distinguish the aggregate call from
    // two per-trip calls (they'd coincide) — only a shared stop can.
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], seatsUsed: 1 })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], seatsUsed: 1, pickupAt: a.pickupAt })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)

    const gate = W.offices[0]!.gates[0]!
    const leg = RP.route(a.pickupAt, gate.at) // identical pickup -> gate leg for both
    const correct = leg.minutes + boardingMinutes(1, 2) // 1 distinct stop, 2 pax, ONCE
    const wrong = leg.minutes + boardingMinutes(1, 1) * 2 // the bug this guards against

    expect(c.minutes).toBeCloseTo(correct, 9)
    expect(c.minutes).not.toBeCloseTo(wrong, 6)
  })

  it('case 5: the first-picked-up passenger has the LARGER added minutes', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], pickupAt: { lat: 12.950, lng: 77.600 } })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.930, lng: 77.630 } })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    expect(c.perPassengerAddedMin['e1']).toBeGreaterThan(c.perPassengerAddedMin['e2']!)
  })

  it('case 6: buildCandidate is deterministic — same args, deep-equal result', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'] })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.940, lng: 77.610 } })
    const c1 = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    const c2 = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    expect(c1).toEqual(c2)
  })

  it('case 7: does not mutate the input trips array or its elements', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'] })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.940, lng: 77.610 } })
    const trips = [a, b]
    const snapshot = JSON.parse(JSON.stringify(trips))
    buildCandidate(trips, [1, 0], 'v-sedan', 'd-fresh', W, RP)
    expect(trips).toEqual(snapshot)
    expect(trips[0]).toBe(a) // same references, not replaced
    expect(trips[1]).toBe(b)
  })
})

describe('buildCandidate — direction (logout)', () => {
  it('logout, single trip: perPassengerAddedMin is exactly 0 (not an epsilon)', () => {
    const trip = makeTrip({ direction: 'logout' })
    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, RP)
    expect(c.perPassengerAddedMin['e1']).toBe(0)
  })

  it('logout, two trips: the LAST-dropped rider carries the larger added minutes', () => {
    // a is dropped first (order [0,1]), b last -- mirror of case 5.
    const a = makeTrip({
      id: 'ta', employeeIds: ['e1'], direction: 'logout',
      pickupAt: { lat: 12.950, lng: 77.600 },
    })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], direction: 'logout',
      pickupAt: { lat: 12.930, lng: 77.630 },
    })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)
    expect(c.perPassengerAddedMin['e2']).toBeGreaterThan(c.perPassengerAddedMin['e1']!)
  })

  it('logout km is the gate->drop->drop sum, NOT the login-sequence sum for the same trips', () => {
    const a = makeTrip({
      id: 'ta', employeeIds: ['e1'], direction: 'logout',
      pickupAt: { lat: 12.950, lng: 77.600 },
    })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], direction: 'logout',
      pickupAt: { lat: 12.930, lng: 77.630 },
    })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)

    const gate = W.offices[0]!.gates[0]!
    const logoutSum = RP.route(gate.at, a.pickupAt).km + RP.route(a.pickupAt, b.pickupAt).km
    const loginSequenceSum = RP.route(a.pickupAt, b.pickupAt).km + RP.route(b.pickupAt, gate.at).km

    expect(c.km).toBeCloseTo(logoutSum, 9)
    expect(c.km).not.toBeCloseTo(loginSequenceSum, 6)
  })

  it('mixed directions in one order throws, naming both directions', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], direction: 'login' })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], direction: 'logout' })
    expect(() => buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)).toThrow(/login/)
    expect(() => buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)).toThrow(/logout/)
  })

  it('under an ASYMMETRIC route, a solo logout rider still gets exactly 0 -- proves soloMinutes really routes gate -> home', () => {
    const trip = makeTrip({ direction: 'logout' })
    const gate = W.offices[0]!.gates[0]!
    // home -> gate is cheap (10 min), gate -> home is expensive (30 min) --
    // only correct direction-aware routing keeps solo == candidate for both.
    const arp = directionalRP(trip.pickupAt, gate.at, 10, 30)
    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, arp)
    expect(c.minutes).toBeCloseTo(30 + boardingMinutes(1, trip.seatsUsed), 9)
    expect(soloMinutes(trip, W, arp)).toBe(c.minutes)
    expect(c.perPassengerAddedMin['e1']).toBe(0)
  })

  it('the same-direction guard does not fire on a valid single-direction group', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], direction: 'logout' })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], direction: 'logout',
      pickupAt: { lat: 12.940, lng: 77.610 },
    })
    expect(() => buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)).not.toThrow()
  })
})

describe('soloMinutes', () => {
  it('equals what a one-trip buildCandidate produces for minutes (by construction)', () => {
    const trip = makeTrip()
    const solo = soloMinutes(trip, W, RP)
    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, RP)
    expect(solo).toBe(c.minutes)
  })

  it('is route minutes plus one-stop boarding for that trip alone', () => {
    const trip = makeTrip()
    const gate = W.offices[0]!.gates[0]!
    const leg = RP.route(trip.pickupAt, gate.at)
    expect(soloMinutes(trip, W, RP)).toBeCloseTo(leg.minutes + boardingMinutes(1, trip.seatsUsed), 9)
  })

  it('routes gate -> home for a logout, and equals what a one-trip logout buildCandidate produces', () => {
    const trip = makeTrip({ direction: 'logout' })
    const gate = W.offices[0]!.gates[0]!
    const leg = RP.route(gate.at, trip.pickupAt) // gate -> home, not home -> gate
    expect(soloMinutes(trip, W, RP)).toBeCloseTo(leg.minutes + boardingMinutes(1, trip.seatsUsed), 9)

    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, RP)
    expect(soloMinutes(trip, W, RP)).toBe(c.minutes)
  })
})
