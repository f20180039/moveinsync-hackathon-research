/**
 * PURPOSE: build a routed, timed, costed Candidate from a proposed pickup
 *          order — the one function every policy and every solver depends on.
 * PIVOT: to change how detour or boarding time is split across stops, change
 *        it here and nowhere else — every policy reads the result, not the
 *        route directly.
 * SAFE-TO-DELETE: no — buildCandidate is the sole source of Candidate values.
 */
import type { Candidate, Direction, LatLng, Trip, World } from '../core/types'
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
 * Minutes for one trip to travel solo, in the direction-correct order: home
 * -> gate for a login (boarding at home, dropped at the gate), gate -> home
 * for a logout (boarding at the gate, dropped at home). Under the symmetric
 * estimate tier this number is unchanged either way, but an asymmetric route
 * cache would otherwise make a solo LOGOUT rider's own detour non-zero —
 * brief case 1's failure mode arriving by the back door.
 */
export function soloMinutes(t: Trip, w: World, rp: RouteProvider): number {
  const gateAt = resolveGate(w, t.officeId, t.gateId)
  const leg = t.direction === 'logout' ? rp.route(gateAt, t.pickupAt) : rp.route(t.pickupAt, gateAt)
  return leg.minutes + boardingMinutes(1, t.seatsUsed)
}

/**
 * Route, time and cost a proposed grouping. `order` indexes into `trips`.
 * All trips in `order` must share one `direction` — a candidate mixing an
 * inbound and an outbound rider is nonsense, and mixing the sequencing below
 * for the two would silently invert every timing and fairness number.
 *
 * LOGIN: home-side stops in `order`, then distinct gates (first-appearance
 * order) — everyone boards at their own home, all are dropped at the office.
 * LOGOUT: distinct gates (first-appearance order) FIRST, then the home-side
 * stops in `order` — everyone boards at their own gate, all are dropped at
 * home. The generator's logout `windows` are office-DEPARTURE slots, so
 * `start` (the earliest window start) correctly anchors elapsed 0 to the
 * first gate's departure in that case.
 *
 * Pure: never mutates `trips` or its elements.
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

  const directions = new Set<Direction>(ordered.map((t) => t.direction))
  if (directions.size > 1) {
    throw new Error(
      `buildCandidate: cannot mix directions in one candidate (got ${[...directions].join(', ')})`,
    )
  }
  const direction = ordered[0]!.direction

  // distinct gates, in the order they first appear along `ordered` — this
  // is the BOARDING order for a logout, the DROP order for a login.
  const gateIds: string[] = []
  for (const t of ordered) if (!gateIds.includes(t.gateId)) gateIds.push(t.gateId)
  const gatePoints = gateIds.map((gid) => {
    const owner = ordered.find((t) => t.gateId === gid)!
    return resolveGate(w, owner.officeId, gid)
  })
  // seats boarding/alighting at each distinct gate — gates ARE deduped
  // (unlike home stops), so a shared gate aggregates every rider on it.
  const gateSeats = gateIds.map((gid) =>
    ordered.filter((t) => t.gateId === gid).reduce((a, t) => a + t.seatsUsed, 0),
  )
  const homePoints = ordered.map((t) => t.pickupAt)

  // Physical visit sequence for km / aggregate minutes.
  const points: LatLng[] =
    direction === 'login' ? [...homePoints, ...gatePoints] : [...gatePoints, ...homePoints]
  let km = 0
  let legMinutes = 0
  for (let i = 1; i < points.length; i++) {
    const leg = rp.route(points[i - 1]!, points[i]!)
    km += leg.km
    legMinutes += leg.minutes
  }

  // distinct HOME-side stop locations (exact lat/lng), excluding gates, in
  // EITHER direction — the per-stop/per-passenger boarding split (A9),
  // applied ONCE, aggregated.
  const distinctStops = new Set(ordered.map((t) => `${t.pickupAt.lat},${t.pickupAt.lng}`)).size
  const totalPax = ordered.reduce((a, t) => a + t.seatsUsed, 0)
  const minutes = legMinutes + boardingMinutes(distinctStops, totalPax)

  // Relative-elapsed simulation (never accumulated directly on the epoch-ms
  // `start` — see the float-cancellation note below) along the SAME
  // boarding-side-first sequence as km/minutes above.
  const start = Math.min(...trips.map((t) => Math.min(...t.windows.map((win) => win[0]))))
  const homeElapsed: number[] = new Array(ordered.length)
  const gateElapsed: number[] = new Array(gateIds.length)

  if (direction === 'login') {
    // board at each home in turn (not deduped — one stop per trip)...
    homeElapsed[0] = 0
    for (let i = 1; i < ordered.length; i++) {
      const leg = rp.route(ordered[i - 1]!.pickupAt, ordered[i]!.pickupAt)
      homeElapsed[i] = homeElapsed[i - 1]! + leg.minutes + boardingMinutes(1, ordered[i - 1]!.seatsUsed)
    }
    // ...then drop at each gate; nobody boards at a gate on an inbound run.
    const lastHome = ordered[ordered.length - 1]!
    gateElapsed[0] =
      homeElapsed[ordered.length - 1]! +
      rp.route(lastHome.pickupAt, gatePoints[0]!).minutes +
      boardingMinutes(1, lastHome.seatsUsed)
    for (let i = 1; i < gatePoints.length; i++) {
      gateElapsed[i] = gateElapsed[i - 1]! + rp.route(gatePoints[i - 1]!, gatePoints[i]!).minutes
    }
  } else {
    // board at each gate in turn (deduped — one stop per distinct gate)...
    gateElapsed[0] = 0
    for (let i = 1; i < gatePoints.length; i++) {
      const leg = rp.route(gatePoints[i - 1]!, gatePoints[i]!)
      gateElapsed[i] = gateElapsed[i - 1]! + leg.minutes + boardingMinutes(1, gateSeats[i - 1]!)
    }
    // ...then drop at each home; nobody boards again at a home drop.
    const lastGateIdx = gatePoints.length - 1
    homeElapsed[0] =
      gateElapsed[lastGateIdx]! +
      rp.route(gatePoints[lastGateIdx]!, ordered[0]!.pickupAt).minutes +
      boardingMinutes(1, gateSeats[lastGateIdx]!)
    for (let i = 1; i < ordered.length; i++) {
      const leg = rp.route(ordered[i - 1]!.pickupAt, ordered[i]!.pickupAt)
      homeElapsed[i] = homeElapsed[i - 1]! + leg.minutes
    }
  }

  // pickupTimes: epoch ms at which this trip's HOME-side stop is served —
  // board time inbound (login), drop time outbound (logout). Name kept
  // (see core/types.ts) even though its meaning is now direction-dependent.
  const pickupTimes: Record<string, number> = {}
  ordered.forEach((t, i) => { pickupTimes[t.id] = start + homeElapsed[i]! })

  const gateElapsedById: Record<string, number> = {}
  gateIds.forEach((gid, i) => { gateElapsedById[gid] = gateElapsed[i]! })

  // perPassengerAddedMin: this employee's own ride duration (the elapsed
  // time between THEIR two stops — home and their trip's gate, both
  // relative so no cancellation) minus what they'd take solo. Clamped at 0.
  const perPassengerAddedMin: Record<string, number> = {}
  ordered.forEach((trip, i) => {
    const rideDuration =
      direction === 'login'
        ? gateElapsedById[trip.gateId]! - homeElapsed[i]!
        : homeElapsed[i]! - gateElapsedById[trip.gateId]!
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
