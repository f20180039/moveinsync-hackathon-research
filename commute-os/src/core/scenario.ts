/**
 * PURPOSE: the single source of every number the UI shows, plus plan comparison.
 * PIVOT: new headline metric? Add it to Metrics in types.ts and compute it here
 *        — never in a component.
 * SAFE-TO-DELETE: no — KpiStrip, the savings cards and the diff all read this.
 */
import type { Metrics, PolicyStatus, Trip, World } from './types'
import { classOf, cabCostInr, co2Kg } from './ledger'
import type { RouteProvider } from './routing'
import { compareTiers } from './policy'

const ZERO: Metrics = {
  cabKm: 0, shuttleKm: 0, metroPaxKm: 0, vehiclesUsed: 0,
  theoreticalFloorVehicles: 0, avgOccupancyPct: 0, costInr: 0, co2Kg: 0,
  waitingMin: 0, slaViolations: 0, unassignedCount: 0,
}

/**
 * Bin-packing lower bound on fleet size: ceil(total passengers / seats).
 * No routing, however clever, can beat this — which is why showing it next to
 * baseline and achieved lets you state your own optimality gap (spec 05 §4.2).
 */
export function theoreticalFloor(trips: Trip[], seats: number): number {
  const passengers = trips.reduce((a, t) => a + t.seatsUsed, 0)
  if (passengers === 0) return 0
  if (seats <= 0) return passengers
  return Math.ceil(passengers / seats)
}

/** Every displayed number derives from here. */
export function computeMetrics(trips: Trip[], w: World, rp: RouteProvider): Metrics {
  if (trips.length === 0) return { ...ZERO }

  const m: Metrics = { ...ZERO }
  const costed: Trip[] = []
  let seatsOffered = 0
  let passengers = 0

  for (const t of trips) {
    const vehicle = w.vehicles.find((v) => v.id === t.vehicleId)
    const office = w.offices.find((o) => o.id === t.officeId)
    const gate = office?.gates.find((g) => g.id === t.gateId)
    if (!vehicle || !gate) { m.unassignedCount++; continue }

    const leg = rp.route(t.pickupAt, gate.at)
    const cls = classOf(vehicle)

    if (cls === 'shuttle') m.shuttleKm += leg.km
    else m.cabKm += leg.km

    m.costInr += cabCostInr(leg.km, leg.minutes, cls)
    m.co2Kg += co2Kg(leg.km, cls, vehicle.fuel)

    // Per DISPATCH, not per distinct vehicle asset: the same 4-seat cab making
    // 5 sequential runs offers 5 x 4 seats across the day, not 4 total. The
    // design's own "174 cabs -> 138 -> floor 50" headline for ~200 trips is
    // counting cab RUNS, and the floor (ceil(passengers/seats) over dispatches)
    // is only comparable to vehiclesUsed if both count the same unit.
    seatsOffered += vehicle.seats
    passengers += t.seatsUsed
    costed.push(t)
  }

  m.vehiclesUsed = costed.length
  // LOOSE bound: it assumes an idealised fleet made entirely of the fleet's
  // largest-capacity vehicle. That is the correct lower bound for "fewest
  // dispatches given the best possible packing" once shuttles are in the mix
  // — a floor pinned to a smaller cab-only unit would overstate the vehicles
  // needed and could exceed a legitimately lower vehiclesUsed. Empty fleet ->
  // 0, matching theoreticalFloor's own seats <= 0 fallback to passenger count.
  const floorSeats = w.vehicles.length > 0 ? Math.max(...w.vehicles.map((v) => v.seats)) : 0
  m.theoreticalFloorVehicles = theoreticalFloor(costed, floorSeats)
  m.avgOccupancyPct = seatsOffered === 0 ? 0 : (passengers / seatsOffered) * 100
  return m
}

/**
 * Improvement, expressed so every field reads "higher is better":
 * reductions for cost/km/carbon/vehicles, a gain for occupancy.
 */
export function diffMetrics(baseline: Metrics, solved: Metrics): Metrics {
  return {
    cabKm: baseline.cabKm - solved.cabKm,
    shuttleKm: baseline.shuttleKm - solved.shuttleKm,
    metroPaxKm: solved.metroPaxKm - baseline.metroPaxKm,
    vehiclesUsed: baseline.vehiclesUsed - solved.vehiclesUsed,
    // NOT a subtraction: the floor is a property of DEMAND, not of either
    // plan's quality. With passengers conserved it is identical in both, so
    // baseline - solved is always 0 and reads as an achievement nobody
    // delivered — and a genuinely lower floor (fewer passengers) would not be
    // an improvement either. Pass it through from `solved` unchanged.
    theoreticalFloorVehicles: solved.theoreticalFloorVehicles,
    avgOccupancyPct: solved.avgOccupancyPct - baseline.avgOccupancyPct,
    costInr: baseline.costInr - solved.costInr,
    co2Kg: baseline.co2Kg - solved.co2Kg,
    waitingMin: baseline.waitingMin - solved.waitingMin,
    slaViolations: baseline.slaViolations - solved.slaViolations,
    unassignedCount: baseline.unassignedCount - solved.unassignedCount,
  }
}

/**
 * Savings as a range, never a point estimate: a merge whose saving depends on
 * everyone turning up is worth less than one that does not. p10 assumes the
 * risk lands badly.
 */
export function savingsBand(
  expectedInr: number, noShowRisk: number,
): { p10Inr: number; expectedInr: number; p90Inr: number } {
  const risk = Math.min(1, Math.max(0, noShowRisk))
  return {
    p10Inr: Math.max(0, expectedInr * (1 - risk)),
    expectedInr,
    p90Inr: expectedInr,
  }
}

/**
 * Lexicographic plan comparison: tier first, cost only as a tie-break.
 * This is the mechanism that stops kilometre savings outranking an unserved
 * employee (design v1.1 A1).
 */
export function comparePlans(
  a: { tier: PolicyStatus; metrics: Metrics },
  b: { tier: PolicyStatus; metrics: Metrics },
): number {
  const byTier = compareTiers(a.tier, b.tier)
  if (byTier !== 0) return byTier
  return a.metrics.costInr - b.metrics.costInr
}
