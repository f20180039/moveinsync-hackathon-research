import { describe, it, expect } from 'vitest'
import { buildCandidate, soloMinutes } from '../../src/solvers/candidate'
import { createRouteProvider, type RouteProvider } from '../../src/core/routing'
import { boardingMinutes } from '../../src/core/ledger'
import { timeWindow } from '../../src/core/policies/time-window'
import { makeWorld, makeTrip, makeCtx, T0 } from '../helpers/world'
import type { LatLng } from '../../src/core/types'

const W = makeWorld()
const RP = createRouteProvider({}) // estimate tier only — deterministic
const MIN = 60_000

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

    // Two riders at the IDENTICAL address must get the SAME fairness number
    // -- a coincident pickup is exactly the case a pooling product should
    // handle best, not worse than two riders who happen to differ by a
    // fraction of a km. Regression guard for the un-deduped per-rider walk.
    expect(c.perPassengerAddedMin['e1']).toBe(c.perPassengerAddedMin['e2'])
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

describe('buildCandidate — pickupTimes VALUE (units: epoch ms, not epoch-plus-raw-minutes)', () => {
  it('login, single trip: pickupTimes is exactly `start`, in epoch ms', () => {
    const trip = makeTrip()
    const c = buildCandidate([trip], [0], 'v-sedan', 'd-fresh', W, RP)
    expect(c.pickupTimes['t1']).toBe(T0)
  })

  it('login, two trips: pickupTimes[second] is start + (leg minutes + boarding) CONVERTED TO MS', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], pickupAt: { lat: 12.950, lng: 77.600 } })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.930, lng: 77.630 } })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)

    const legAB = RP.route(a.pickupAt, b.pickupAt).minutes
    const boardAtA = boardingMinutes(1, a.seatsUsed)
    const expectedB = T0 + (legAB + boardAtA) * MIN

    expect(c.pickupTimes['ta']).toBe(T0)
    expect(c.pickupTimes['tb']).toBe(expectedB)
    // A minutes-as-milliseconds bug would put this well under 1 real second
    // past T0 for a ~16-real-minute leg; a correctly-converted value is well
    // past a full real minute.
    expect(c.pickupTimes['tb']! - T0).toBeGreaterThan(MIN)
  })

  it('logout, single trip: pickupTimes is the DROP time, start + (gate->home + boarding) in ms', () => {
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], direction: 'logout', pickupAt: { lat: 12.950, lng: 77.600 } })
    const gate = W.offices[0]!.gates[0]!
    const c = buildCandidate([a], [0], 'v-sedan', 'd-fresh', W, RP)

    const legGateHome = RP.route(gate.at, a.pickupAt).minutes
    const boardAtGate = boardingMinutes(1, a.seatsUsed)
    const expected = T0 + (legGateHome + boardAtGate) * MIN

    expect(c.pickupTimes['ta']).toBe(expected)
    expect(c.pickupTimes['ta']! - T0).toBeGreaterThan(MIN)
  })

  it('`start` is anchored to `ordered`, not a superset `trips` array (Finding 4)', () => {
    // An outlying trip NOT in `order` has an earlier window than the two
    // real candidate members. If `start` were pulled from the full `trips`
    // array, both real trips' pickupTimes would shift 30 real minutes early.
    const outlier = makeTrip({ id: 'outlier', windows: [[T0 - 30 * MIN, T0 - 20 * MIN]] })
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'] })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.940, lng: 77.610 } })
    const trips = [outlier, a, b]
    const c = buildCandidate(trips, [1, 2], 'v-sedan', 'd-fresh', W, RP)

    expect(c.pickupTimes['ta']).toBe(T0) // NOT T0 - 30min
  })
})

describe('buildCandidate — walk/aggregate identity (Finding 2 fix)', () => {
  it('c.minutes equals the sum of per-stop boarding charges from the same walk, by construction', () => {
    // Two distinct home stops: (a,b) coincide at one address, c is elsewhere.
    // The aggregate uses ONE boardingMinutes(distinctStops=2, totalPax=4) call;
    // the walk charges boardingMinutes(1, seatsAtStop) once per stop. These
    // MUST agree -- boardingMinutes is linear in stops and pax separately, so
    // distinctStops*setup + totalPax*service telescopes to the same total
    // either way IF (and only if) both paths agree on what "one stop" is.
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], seatsUsed: 1 })
    const b = makeTrip({ id: 'tb', employeeIds: ['e2'], seatsUsed: 1, pickupAt: a.pickupAt })
    const cc = makeTrip({ id: 'tc', employeeIds: ['e3'], seatsUsed: 2, pickupAt: { lat: 12.941, lng: 77.617 } })
    const c = buildCandidate([a, b, cc], [0, 1, 2], 'v-sedan', 'd-fresh', W, RP)

    const gate = W.offices[0]!.gates[0]!
    const legStop0Stop1 = RP.route(a.pickupAt, cc.pickupAt).minutes // (a,b) -> c
    const legStop1Gate = RP.route(cc.pickupAt, gate.at).minutes

    const walkTotal =
      legStop0Stop1 + boardingMinutes(1, 2) /* stop 0: a+b, 2 pax */ +
      legStop1Gate + boardingMinutes(1, 2) /* stop 1: c, 2 pax */

    const distinctStops = 2
    const totalPax = 1 + 1 + 2
    const aggregateForm = legStop0Stop1 + legStop1Gate + boardingMinutes(distinctStops, totalPax)

    expect(c.minutes).toBeCloseTo(walkTotal, 9)
    expect(c.minutes).toBeCloseTo(aggregateForm, 9)
    expect(walkTotal).toBeCloseTo(aggregateForm, 9) // the identity itself
  })
})

describe('buildCandidate x time-window policy (integration)', () => {
  it('a real buildCandidate output, fed into the real time-window policy, passes for a window that genuinely accommodates it', () => {
    // b's real pickup is ~16 real minutes after group start (see the
    // pickupTimes VALUE tests above for the exact figure) -- give it a
    // window that comfortably covers that, and a-checked window at T0.
    const a = makeTrip({ id: 'ta', employeeIds: ['e1'], pickupAt: { lat: 12.950, lng: 77.600 } })
    const b = makeTrip({
      id: 'tb', employeeIds: ['e2'], pickupAt: { lat: 12.930, lng: 77.630 },
      windows: [[T0, T0 + 30 * MIN]],
    })
    const c = buildCandidate([a, b], [0, 1], 'v-sedan', 'd-fresh', W, RP)

    const verdict = timeWindow(c, W, makeCtx())
    expect(verdict.status).toBe('pass')
    expect(verdict.reason).toBe('All pickups inside their windows')
  })
})
