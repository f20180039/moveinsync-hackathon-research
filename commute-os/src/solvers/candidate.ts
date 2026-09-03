/**
 * PURPOSE: build a routed, timed, costed Candidate from a proposed pickup
 *          order — the one function every policy and every solver depends on.
 * PIVOT: to change how detour or boarding time is split across stops, change
 *        it here and nowhere else — every policy reads the result, not the
 *        route directly.
 * SAFE-TO-DELETE: no — buildCandidate is the sole source of Candidate values.
 */
import type { Candidate, LatLng, Trip, World } from '../core/types'
import type { RouteProvider } from '../core/routing'
import { boardingMinutes } from '../core/ledger'

function resolveGate(w: World, officeId: string, gateId: string): LatLng {
  const office = w.offices.find((o) => o.id === officeId)
  if (!office) throw new Error(`buildCandidate: unknown office "${officeId}"`)
  const gate = office.gates.find((g) => g.id === gateId)
  if (!gate) throw new Error(`buildCandidate: unknown gate "${gateId}" on office "${officeId}"`)
  return gate.at
}

/**
 * Minutes for one trip to travel solo: pickup straight to its own gate, plus
 * the boarding time for that one stop. This MUST equal what a one-trip
 * `buildCandidate` produces for `minutes` — perPassengerAddedMin is measured
 * against it, and a mismatch would make a solo rider's own detour non-zero.
 */
export function soloMinutes(t: Trip, w: World, rp: RouteProvider): number {
  const gateAt = resolveGate(w, t.officeId, t.gateId)
  return rp.route(t.pickupAt, gateAt).minutes + boardingMinutes(1, t.seatsUsed)
}

/**
 * Route, time and cost a proposed grouping. `order` indexes into `trips`
 * (pickup visit order); the office gate(s) are visited after every pickup,
 * one stop per distinct gate, in first-appearance order. Pure: never mutates
 * `trips` or its elements.
 */
export function buildCandidate(
  trips: Trip[],
  order: number[],
  vehicleId: string,
  driverId: string,
  w: World,
  rp: RouteProvider,
): Candidate {
  const ordered = order.map((i) => trips[i]!)

  // distinct gates, in the order they first appear along the pickup sequence
  const gateIds: string[] = []
  for (const t of ordered) if (!gateIds.includes(t.gateId)) gateIds.push(t.gateId)
  const gatePoints = gateIds.map((gid) => {
    const owner = ordered.find((t) => t.gateId === gid)!
    return resolveGate(w, owner.officeId, gid)
  })

  // km / aggregate minutes: sum every leg along pickups -> gate -> gate ...
  const points: LatLng[] = [...ordered.map((t) => t.pickupAt), ...gatePoints]
  let km = 0
  let legMinutes = 0
  for (let i = 1; i < points.length; i++) {
    const leg = rp.route(points[i - 1]!, points[i]!)
    km += leg.km
    legMinutes += leg.minutes
  }

  // distinct pickup LOCATIONS (exact lat/lng), excluding gates — the
  // per-stop/per-passenger boarding split (A9), applied ONCE, aggregated.
  const distinctStops = new Set(ordered.map((t) => `${t.pickupAt.lat},${t.pickupAt.lng}`)).size
  const totalPax = ordered.reduce((a, t) => a + t.seatsUsed, 0)
  const minutes = legMinutes + boardingMinutes(distinctStops, totalPax)

  // Cumulative pickup timing, starting from the earliest window start across
  // the group. Each subsequent pickup = previous pickup time + the leg into
  // it + the boarding time incurred AT the previous stop. Accumulated as
  // RELATIVE minutes-since-start first, and only added to `start` (an epoch
  // ms ~1.7e12) at the very end — subtracting two "start + small" values
  // later to get a duration loses precision to floating-point cancellation
  // at that magnitude, and case 1 needs an EXACT zero, not an epsilon.
  const start = Math.min(...trips.map((t) => Math.min(...t.windows.map((win) => win[0]))))
  const pickupElapsed: number[] = [0]
  for (let i = 1; i < ordered.length; i++) {
    const leg = rp.route(ordered[i - 1]!.pickupAt, ordered[i]!.pickupAt)
    pickupElapsed[i] = pickupElapsed[i - 1]! + leg.minutes + boardingMinutes(1, ordered[i - 1]!.seatsUsed)
  }
  const pickupTimes: Record<string, number> = {}
  ordered.forEach((t, i) => { pickupTimes[t.id] = start + pickupElapsed[i]! })

  // Continue the same relative simulation through the gate arrivals: the
  // last pickup's boarding happens before departing for the first gate;
  // gate-to-gate legs carry no further boarding (nobody boards at a gate).
  const lastPickup = ordered[ordered.length - 1]!
  const lastElapsed = pickupElapsed[pickupElapsed.length - 1]!
  const gateElapsed: Record<string, number> = {}
  let ge =
    lastElapsed + rp.route(lastPickup.pickupAt, gatePoints[0]!).minutes + boardingMinutes(1, lastPickup.seatsUsed)
  gateElapsed[gateIds[0]!] = ge
  for (let i = 1; i < gatePoints.length; i++) {
    ge += rp.route(gatePoints[i - 1]!, gatePoints[i]!).minutes
    gateElapsed[gateIds[i]!] = ge
  }

  // perPassengerAddedMin: this employee's own ride duration (their gate's
  // elapsed time minus THEIR pickup's elapsed time — both relative, so no
  // cancellation) minus what they'd take solo. Clamped at 0 — never a
  // negative "saving" here.
  const perPassengerAddedMin: Record<string, number> = {}
  ordered.forEach((trip, i) => {
    const rideDuration = gateElapsed[trip.gateId]! - pickupElapsed[i]!
    const added = Math.max(0, rideDuration - soloMinutes(trip, w, rp))
    for (const eid of trip.employeeIds) perPassengerAddedMin[eid] = added
  })

  return {
    tripIds: ordered.map((t) => t.id),
    trips: ordered,
    vehicleId,
    driverId,
    km,
    minutes,
    perPassengerAddedMin,
    gateIds,
    seatsUsed: totalPax,
    pickupTimes,
  }
}
