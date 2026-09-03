import { describe, it, expect } from 'vitest'
import {
  theoreticalFloor, computeMetrics, diffMetrics, savingsBand, comparePlans,
} from '../../src/core/scenario'
import { createRouteProvider } from '../../src/core/routing'
import { makeWorld, makeTrip } from '../helpers/world'
import type { Metrics } from '../../src/core/types'

const W = makeWorld()
const RP = createRouteProvider({}) // estimate tier only — deterministic

describe('theoreticalFloor', () => {
  it('is the bin-packing bound: passengers over seats, rounded up', () => {
    const trips = Array.from({ length: 10 }, (_, i) => makeTrip({ id: `t${i}`, seatsUsed: 1 }))
    expect(theoreticalFloor(trips, 4)).toBe(3) // ceil(10/4)
  })

  it('handles multi-seat trips', () => {
    const trips = [makeTrip({ id: 'a', seatsUsed: 3 }), makeTrip({ id: 'b', seatsUsed: 3 })]
    expect(theoreticalFloor(trips, 4)).toBe(2) // ceil(6/4)
  })

  it('is zero for no trips', () => {
    expect(theoreticalFloor([], 4)).toBe(0)
  })

  it('never returns less than one for a non-empty set', () => {
    expect(theoreticalFloor([makeTrip()], 12)).toBe(1)
  })

  it('guards against a zero seat count instead of dividing by zero', () => {
    // With no capacity, packing is impossible and the floor degenerates to one
    // vehicle per passenger. Asserting only isFinite() would pass for any
    // finite wrong answer, including 0.
    expect(theoreticalFloor([makeTrip()], 0)).toBe(1)
    expect(theoreticalFloor(
      [makeTrip({ id: 'a' }), makeTrip({ id: 'b' }), makeTrip({ id: 'c' })], 0,
    )).toBe(3)
  })
})

describe('computeMetrics', () => {
  it('counts one dispatch per costed trip, NOT one per distinct vehicleId', () => {
    // v-sedan runs twice (two sequential dispatches) and v-ev once: the pitch's
    // own "174 cabs -> 138 -> floor 50" headline for ~200 trips is counting cab
    // RUNS, so vehiclesUsed must be comparable to that — and to the floor,
    // which is also computed per dispatch.
    const trips = [
      makeTrip({ id: 'a', vehicleId: 'v-sedan' }),
      makeTrip({ id: 'b', vehicleId: 'v-ev' }),
      makeTrip({ id: 'c', vehicleId: 'v-sedan' }),
    ]
    expect(computeMetrics(trips, W, RP).vehiclesUsed).toBe(3)
  })

  it('reports the theoretical floor alongside actual usage', () => {
    // The shared fixture defines only 4 vehicles (v-sedan, v-ev, v-ev-low,
    // v-shuttle). computeMetrics SKIPS any trip whose vehicle does not resolve,
    // so referencing v0..v7 against the default world silently drops all 8 trips
    // and yields vehiclesUsed 0 — the world has to be widened for this case.
    const vehicles = Array.from({ length: 8 }, (_, i) => ({
      id: `v${i}`, plate: `KA01XX${1000 + i}`, seats: 4, fuel: 'ICE' as const,
    }))
    const w = makeWorld({ vehicles })
    const trips = Array.from({ length: 8 }, (_, i) =>
      makeTrip({ id: `t${i}`, vehicleId: `v${i}`, seatsUsed: 1 }))
    const m = computeMetrics(trips, w, RP)
    expect(m.vehiclesUsed).toBe(8)
    expect(m.theoreticalFloorVehicles).toBe(2) // ceil(8/4)
    expect(m.theoreticalFloorVehicles).toBeLessThan(m.vehiclesUsed)
  })

  it('derives the floor unit from the largest vehicle in the fleet, not a hard-coded 4', () => {
    // Mirrors the real fixture shape (4/6/12-seat vehicles). Once solvers pool
    // passengers onto 12-seat shuttles, a floor pinned to 4 overstates the
    // vehicles needed and can exceed a legitimately lower vehiclesUsed,
    // inverting the headline "achieved vs floor" comparison.
    const vehicles = [
      { id: 'v-a', plate: 'KA01A0001', seats: 4, fuel: 'ICE' as const },
      { id: 'v-b', plate: 'KA01A0002', seats: 6, fuel: 'ICE' as const },
      { id: 'v-c', plate: 'KA01A0003', seats: 12, fuel: 'CNG' as const },
    ]
    const w = makeWorld({ vehicles })
    const trips = Array.from({ length: 24 }, (_, i) =>
      makeTrip({ id: `t${i}`, vehicleId: 'v-a', seatsUsed: 1 }))
    const m = computeMetrics(trips, w, RP)
    const maxSeats = Math.max(...vehicles.map((v) => v.seats))
    // ceil(24/12) = 2, NOT ceil(24/4) = 6
    expect(m.theoreticalFloorVehicles).toBe(Math.ceil(24 / maxSeats))
  })

  it('SILENTLY EXCLUDES a trip whose vehicle does not resolve', () => {
    // Documenting a real hazard rather than leaving it to be rediscovered.
    // The guard is deliberate — a metrics call must not throw mid-render — but
    // it must be KNOWN: anything upstream owns referential integrity, which is
    // what the fixture test in the next task enforces.
    const m = computeMetrics([makeTrip({ vehicleId: 'does-not-exist' })], W, RP)
    expect(m.vehiclesUsed).toBe(0)
    expect(m.cabKm).toBe(0)
    expect(m.costInr).toBe(0)
    // The drop is deliberate, but it must no longer be invisible.
    expect(m.unassignedCount).toBe(1)
  })

  it('SILENTLY EXCLUDES a trip whose gate does not resolve, on a valid office', () => {
    // A bad gateId on a VALID office used to fall back to that office's first
    // gate, producing a plausible-but-wrong distance instead of a zero — worse
    // than the vehicle path, and inconsistent with it. Both must now skip.
    const m = computeMetrics([makeTrip({ gateId: 'does-not-exist' })], W, RP)
    expect(m.vehiclesUsed).toBe(0)
    expect(m.cabKm).toBe(0)
    expect(m.costInr).toBe(0)
    // The drop is deliberate, but it must no longer be invisible.
    expect(m.unassignedCount).toBe(1)
  })

  it('accumulates cab km from the route provider', () => {
    const m = computeMetrics([makeTrip()], W, RP)
    expect(m.cabKm).toBeCloseTo(7.4043, 3)
    expect(m.costInr).toBeCloseTo(253.86, 1)
    expect(m.co2Kg).toBeCloseTo(1.0514, 3)
  })

  it('separates shuttle km from cab km', () => {
    const m = computeMetrics([makeTrip({ vehicleId: 'v-shuttle' })], W, RP)
    expect(m.shuttleKm).toBeGreaterThan(0)
    expect(m.cabKm).toBe(0)
  })

  it('computes average occupancy as passengers over seats offered', () => {
    // two 4-seat cabs, 1 + 3 passengers => 4/8 = 50%
    const trips = [
      makeTrip({ id: 'a', vehicleId: 'v-sedan', seatsUsed: 1 }),
      makeTrip({ id: 'b', vehicleId: 'v-ev', seatsUsed: 3 }),
    ]
    expect(computeMetrics(trips, W, RP).avgOccupancyPct).toBeCloseTo(50, 6)
  })

  it('returns an all-zero metric set for no trips', () => {
    const m = computeMetrics([], W, RP)
    expect(m.vehiclesUsed).toBe(0)
    expect(m.cabKm).toBe(0)
    expect(m.avgOccupancyPct).toBe(0)
  })

  it('is deterministic — identical input gives identical output', () => {
    const trips = [makeTrip()]
    expect(computeMetrics(trips, W, RP)).toEqual(computeMetrics(trips, W, RP))
    // a constant-ZERO stub is "deterministic" too — require a real result
    expect(computeMetrics(trips, W, RP).cabKm).toBeGreaterThan(0)
  })
})

describe('diffMetrics', () => {
  const base = { cabKm: 100, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 10,
    theoreticalFloorVehicles: 3, avgOccupancyPct: 40, costInr: 5000, co2Kg: 14,
    waitingMin: 0, slaViolations: 0, unassignedCount: 0 } satisfies Metrics
  const solved = { ...base, cabKm: 70, vehiclesUsed: 7, avgOccupancyPct: 62, costInr: 3600, co2Kg: 10 }

  it('reports improvement as a positive reduction', () => {
    const d = diffMetrics(base, solved)
    expect(d.cabKm).toBe(30)
    expect(d.vehiclesUsed).toBe(3)
    expect(d.costInr).toBe(1400)
    expect(d.co2Kg).toBeCloseTo(4, 6)
  })

  it('reports occupancy as a gain, not a reduction', () => {
    expect(diffMetrics(base, solved).avgOccupancyPct).toBeCloseTo(22, 6)
  })

  it('is all zeros when nothing changed', () => {
    const d = diffMetrics(base, base)
    expect(d.cabKm).toBe(0)
    expect(d.costInr).toBe(0)
    expect(d.avgOccupancyPct).toBe(0)
  })
})

describe('savingsBand', () => {
  it('brackets the expected value', () => {
    const b = savingsBand(410, 0.25)
    expect(b.expectedInr).toBe(410)
    expect(b.p10Inr).toBeLessThan(410)
    expect(b.p90Inr).toBeGreaterThanOrEqual(410)
  })

  it('widens the downside as no-show risk rises', () => {
    expect(savingsBand(410, 0.5).p10Inr).toBeLessThan(savingsBand(410, 0.1).p10Inr)
  })

  it('collapses to a point when risk is zero', () => {
    const b = savingsBand(410, 0)
    expect(b.p10Inr).toBe(410)
    expect(b.p90Inr).toBe(410)
  })

  it('never reports a negative downside', () => {
    // The clamp is unreachable for a non-negative expectation: risk is already
    // bounded to [0,1], so expected*(1-risk) >= 0 and at risk=1 it is exactly 0
    // without the clamp doing anything. Only a NEGATIVE expectation exercises it.
    expect(savingsBand(100, 1).p10Inr).toBeGreaterThanOrEqual(0)
    expect(savingsBand(-100, 0.5).p10Inr).toBe(0)
    expect(savingsBand(-100, 0).p10Inr).toBe(0)
  })
})

describe('comparePlans', () => {
  const m = (costInr: number, unassignedCount = 0): Metrics => ({
    cabKm: 0, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 0,
    theoreticalFloorVehicles: 0, avgOccupancyPct: 0, costInr, co2Kg: 0,
    waitingMin: 0, slaViolations: 0, unassignedCount,
  })

  it('prefers the better tier regardless of cost', () => {
    const cheapButBlocked = { tier: 'block' as const, metrics: m(1) }
    const dearButClean = { tier: 'pass' as const, metrics: m(99_999) }
    expect(comparePlans(dearButClean, cheapButBlocked)).toBeLessThan(0)
  })

  it('prefers serving everyone over saving money — the medium tier rule', () => {
    const dropsSomeone = { tier: 'medium' as const, metrics: m(1) }
    const servesAll = { tier: 'soft' as const, metrics: m(99_999) }
    expect(comparePlans(servesAll, dropsSomeone)).toBeLessThan(0)
  })

  it('falls back to cost only within the same tier', () => {
    expect(comparePlans(
      { tier: 'pass', metrics: m(100) },
      { tier: 'pass', metrics: m(200) },
    )).toBeLessThan(0)
  })
})
