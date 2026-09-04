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

/** Trip.windows / Candidate.pickupTimes are epoch ms; every elapsed-time
 *  accumulator in this file is minutes. Converting exactly once, here. */
const MS_PER_MIN = 60_000

function resolveGate(w: World, officeId: string, gateId: string): LatLng {
  const office = w.offices.find((o) => o.id === officeId)
  if (!office) throw new Error(`buildCandidate: unknown office "${officeId}"`)
  const gate = office.gates.find((g) => g.id === gateId)
  if (!gate) throw new Error(`buildCandidate: unknown gate "${gateId}" on office "${officeId}"`)
  return gate.at
}

/**
 * Minutes for one trip to travel solo, in the direction-correct order: home
 * -> gate for a login, gate -> home for a logout. Under the symmetric
 * estimate tier this number is unchanged either way, but an asymmetric route
 * cache would otherwise make a solo LOGOUT rider's own detour non-zero —
 * brief case 1's failure mode arriving by the back door.
 */
export function soloMinutes(t: Trip, w: World, rp: RouteProvider): number {
  const gateAt = resolveGate(w, t.officeId, t.gateId)
  const leg = t.direction === 'logout' ? rp.route(gateAt, t.pickupAt) : rp.route(t.pickupAt, gateAt)
  return leg.minutes + boardingMinutes(1, t.seatsUsed)
}

type Stop = { at: LatLng; seats: number }

/**
 * Distinct stops, in first-appearance order along `items`, plus which stop
 * each item belongs to. Two trips at the SAME exact point (or same gate)
 * collapse to one stop with aggregated seats — this is what makes coincident
 * pickups share a boarding charge and a ride time instead of double-paying
 * for a "second" stop that never physically happened.
 */
function groupStops(items: Trip[], key: (t: Trip) => string, at: (t: Trip) => LatLng) {
  const order: string[] = []
  const byKey = new Map<string, Stop>()
  const indexOf = items.map((t) => {
    const k = key(t)
    let stop = byKey.get(k)
    if (!stop) { stop = { at: at(t), seats: 0 }; byKey.set(k, stop); order.push(k) }
    stop.seats += t.seatsUsed
    return order.indexOf(k)
  })
  return { stops: order.map((k) => byKey.get(k)!), indexOf }
}

/** Elapsed minutes at each stop in `stops`, relative to 0 at `stops[0]`,
 *  charging `boardingMinutes(1, seats)` once per stop AS IT IS LEFT. */
function walk(stops: Stop[], rp: RouteProvider, chargeBoarding: boolean): number[] {
  const elapsed: number[] = new Array(stops.length)
  elapsed[0] = 0
  for (let i = 1; i < stops.length; i++) {
    const leg = rp.route(stops[i - 1]!.at, stops[i]!.at)
    elapsed[i] = elapsed[i - 1]! + leg.minutes + (chargeBoarding ? boardingMinutes(1, stops[i - 1]!.seats) : 0)
  }
  return elapsed
}

/**
 * Route, time and cost a proposed grouping. `order` indexes into `trips`.
 * All trips in `order` must share one `direction` — a candidate mixing an
 * inbound and an outbound rider is nonsense, and mixing the sequencing below
 * for the two would silently invert every timing and fairness number.
 *
 * LOGIN: board at each distinct home stop (in `order`), then drop at each
 * distinct gate (first-appearance order). LOGOUT: board at each distinct
 * gate, then drop at each distinct home stop. Either way, boarding time is
 * charged once per BOARDING-side stop as it's left; nobody boards again on
 * the drop side. The generator's logout `windows` are office-DEPARTURE
 * slots, so `start` (the earliest window start, over `ordered`) correctly
 * anchors elapsed 0 to the first gate's departure in that case.
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

  // distinct HOME-side stops (exact lat/lng) and distinct GATES, each in
  // first-appearance order along `ordered`. Used for BOTH km/minutes and the
  // per-rider elapsed walk, so the two can never disagree about what "one
  // stop" means the way the pre-fix per-trip walk did.
  const home = groupStops(ordered, (t) => `${t.pickupAt.lat},${t.pickupAt.lng}`, (t) => t.pickupAt)
  const gate = groupStops(ordered, (t) => t.gateId, (t) => resolveGate(w, t.officeId, t.gateId))
  const gateIds = [...new Set(ordered.map((t) => t.gateId))]

  const boarding = direction === 'login' ? home : gate
  const drop = direction === 'login' ? gate : home

  // km / aggregate minutes: sum every leg along the deduped boarding -> drop
  // sequence (a login collapses to home-stops then gates; a logout, the
  // reverse). Distinct stops that coincide contribute no leg at all now,
  // rather than a harmless-but-redundant zero-length one.
  const points: LatLng[] = [...boarding.stops.map((s) => s.at), ...drop.stops.map((s) => s.at)]
  let km = 0
  let legMinutes = 0
  for (let i = 1; i < points.length; i++) {
    const leg = rp.route(points[i - 1]!, points[i]!)
    km += leg.km
    legMinutes += leg.minutes
  }

  // distinct HOME-side stops, in EITHER direction — the per-stop/per-
  // passenger boarding split (A9), applied ONCE, aggregated.
  const distinctStops = home.stops.length
  const totalPax = ordered.reduce((a, t) => a + t.seatsUsed, 0)
  const minutes = legMinutes + boardingMinutes(distinctStops, totalPax)

  // The relative-elapsed walk: boarding-side stops first (boarding charged
  // as each is left), then drop-side stops (no further boarding). Every trip
  // AT a stop shares that stop's elapsed time -- two riders at one address,
  // or one shared gate, are genuinely at the same moment, not two.
  const boardingElapsed = walk(boarding.stops, rp, true)
  const lastBoardingIdx = boarding.stops.length - 1
  const dropElapsed: number[] = new Array(drop.stops.length)
  dropElapsed[0] =
    boardingElapsed[lastBoardingIdx]! +
    rp.route(boarding.stops[lastBoardingIdx]!.at, drop.stops[0]!.at).minutes +
    boardingMinutes(1, boarding.stops[lastBoardingIdx]!.seats)
  for (let i = 1; i < drop.stops.length; i++) {
    dropElapsed[i] = dropElapsed[i - 1]! + rp.route(drop.stops[i - 1]!.at, drop.stops[i]!.at).minutes
  }

  const boardingIndexOf = direction === 'login' ? home.indexOf : gate.indexOf
  const dropIndexOf = direction === 'login' ? gate.indexOf : home.indexOf
  const homeIndexOf = home.indexOf
  const homeElapsed = direction === 'login' ? boardingElapsed : dropElapsed

  // start: earliest window start over `ordered` (NOT the full `trips` param
  // — a solver may pass a superset there, and anchoring to a window outside
  // this candidate would corrupt every timestamp below it).
  const start = Math.min(...ordered.map((t) => Math.min(...t.windows.map((win) => win[0]))))

  // pickupTimes: epoch ms this trip's HOME-side stop is served -- board time
  // inbound (login), drop time outbound (logout). `homeElapsed` is MINUTES;
  // converting to ms exactly once, here, is the whole fix for Finding 1.
  const pickupTimes: Record<string, number> = {}
  ordered.forEach((t, i) => { pickupTimes[t.id] = start + homeElapsed[homeIndexOf[i]!]! * MS_PER_MIN })

  // perPassengerAddedMin: this employee's own ride duration (their drop
  // stop's elapsed time minus THEIR boarding stop's elapsed time -- both
  // relative minutes, so no epoch-scale cancellation) minus what they'd take
  // solo. Clamped at 0.
  const perPassengerAddedMin: Record<string, number> = {}
  ordered.forEach((trip, i) => {
    const rideDuration = dropElapsed[dropIndexOf[i]!]! - boardingElapsed[boardingIndexOf[i]!]!
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
