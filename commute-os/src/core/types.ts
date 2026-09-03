/**
 * PURPOSE: the single contract for the whole domain — all types, zero logic.
 * PIVOT: adding a constraint dimension (luggage, wheelchair) starts here.
 * SAFE-TO-DELETE: no — every module imports from this file.
 */

// ── primitives ──────────────────────────────────────────────────────────────
export type LatLng = { lat: number; lng: number }
export type Fuel = 'ICE' | 'CNG' | 'EV'
export type Direction = 'login' | 'logout'
export type Gender = 'F' | 'M' | 'X'

/** [start, end] in epoch ms, both inclusive. A trip may have several. */
export type Window = [number, number]

// ── places ──────────────────────────────────────────────────────────────────
export type Gate = { id: string; name: string; at: LatLng }
export type Office = { id: string; name: string; at: LatLng; gates: Gate[] }
export type Depot = { id: string; name: string; at: LatLng }

export type Zone = {
  id: string
  name: string
  centroid: LatLng
  /** closed ring; first point is NOT repeated at the end */
  polygon: LatLng[]
  /** 0..1, lowered by repeated admin rejections */
  confidence: number
}

// ── people & fleet ──────────────────────────────────────────────────────────
export type Employee = {
  id: string
  name: string
  gender: Gender
  homeAt: LatLng
  zoneId: string
  officeId: string
  /** historical no-show probability, 0..1 */
  noShowRate: number
}

export type Vehicle = {
  id: string
  plate: string
  seats: number
  fuel: Fuel
  /** EV only: full-charge range in km */
  rangeKm?: number
  /** EV only: state of charge, 0..100 */
  socPct?: number
}

export type Driver = {
  id: string
  name: string
  /** minutes of duty already worked today */
  dutyMinutesToday: number
  /** 0..100 quality score */
  score: number
}

// ── metro ───────────────────────────────────────────────────────────────────
export type MetroStation = {
  /** the dataset's station_code, e.g. "WHTM" */
  id: string
  name: string
  at: LatLng
  /** every line this station belongs to; interchanges have >1 */
  lineIds: string[]
  isInterchange: boolean
}

export type MetroLine = {
  id: string
  name: string
  colour: string
  /** station ids in sequence order */
  stationIds: string[]
  headwayMin: number
}

/** One directed hop. The loader emits BOTH directions for every CSV row. */
export type MetroEdge = { from: string; to: string; km: number; lineId: string }

// ── demand ──────────────────────────────────────────────────────────────────
export type Trip = {
  id: string
  /** an array from the outset: a merged trip is a Trip, not a special case */
  employeeIds: string[]
  pickupAt: LatLng
  zoneId: string
  officeId: string
  gateId: string
  direction: Direction
  /** acceptable pickup slots; ANY window may be satisfied */
  windows: Window[]
  seatsUsed: number
  vehicleId: string
  driverId: string
  /** pickup or drop falls in 21:00–06:00 local */
  isNightShift: boolean
}

export type World = {
  zones: Zone[]
  offices: Office[]
  employees: Employee[]
  vehicles: Vehicle[]
  drivers: Driver[]
  depots: Depot[]
  metroLines: MetroLine[]
  metroStations: MetroStation[]
  metroEdges: MetroEdge[]
}

// ── routing ─────────────────────────────────────────────────────────────────
export type RouteSource = 'cache' | 'estimate'
export type RouteResult = {
  km: number
  minutes: number
  polyline: LatLng[]
  source: RouteSource
}

// ── solver / policy plumbing ────────────────────────────────────────────────
export type Savings = {
  km: number
  inr: number
  co2Kg: number
  /** worst-case detour imposed on any single passenger, minutes */
  minutesAdded: number
  p10Inr: number
  p90Inr: number
}

/** A proposed grouping, already ordered, routed and costed. */
export type Candidate = {
  tripIds: string[]
  /** resolved trips, in proposed pickup order */
  trips: Trip[]
  vehicleId: string
  driverId: string
  km: number
  minutes: number
  /** employeeId -> detour minutes this candidate imposes */
  perPassengerAddedMin: Record<string, number>
  /** distinct gates touched, in visit order */
  gateIds: string[]
  seatsUsed: number
  /** epoch ms at which each trip is actually picked up */
  pickupTimes: Record<string, number>
}

/** Ambient state a policy may need but must not fetch itself. */
export type PolicyCtx = {
  /** simulation time, epoch ms. NEVER read from the system clock. */
  now: number
  /** zoneId -> admin reject count */
  zoneRejections: Record<string, number>
  /** 1.0 = nominal */
  trafficMultiplier: number
  /** slider override of every employee.noShowRate */
  noShowOverride?: number
  /** employeeId -> detour minutes already absorbed this week */
  detourMinutesThisWeek: Record<string, number>
}

/**
 * Four tiers, compared lexicographically and never summed:
 *   block  — hard; never acceptable
 *   medium — serve everyone before optimising
 *   soft   — then be efficient
 *   pass   — no violation
 */
export type PolicyStatus = 'pass' | 'soft' | 'medium' | 'block'

/**
 * VROOM's vocabulary (docs/API.md:445) plus three of ours. The UI renders
 * `cause` directly, so each policy must use the one that actually describes its
 * refusal — a zone-confidence warning displaying "unfair_detour" is simply
 * wrong information in front of an admin.
 */
export type ViolationCause =
  | 'delay'
  | 'lead_time'
  | 'load'
  | 'max_tasks'
  | 'skills'
  | 'precedence'
  | 'missing_break'
  | 'max_travel_time'
  | 'max_distance'
  | 'max_load'
  // ours — no VROOM equivalent
  | 'unfair_detour'
  | 'low_confidence'
  | 'no_show_risk'

export type PolicyVerdict = {
  id: string
  name: string
  status: PolicyStatus
  cause?: ViolationCause
  /** magnitude of the miss; negative means over the limit */
  slack?: { value: number; unit: string }
  reason: string
}

export type PolicyTrace = {
  verdicts: PolicyVerdict[]
  blocked: boolean
  /** the worst status across all verdicts */
  tier: PolicyStatus
}

export type Policy = (c: Candidate, w: World, ctx: PolicyCtx) => PolicyVerdict

// ── metrics ─────────────────────────────────────────────────────────────────
export type Metrics = {
  cabKm: number
  shuttleKm: number
  metroPaxKm: number
  /** count of costed DISPATCHES (cab runs), not distinct vehicle assets — one
   *  vehicle making 5 sequential runs counts as 5, comparable to the floor below */
  vehiclesUsed: number
  /** bin-packing floor: no routing can beat this */
  theoreticalFloorVehicles: number
  avgOccupancyPct: number
  costInr: number
  co2Kg: number
  /** total minutes passengers wait because a vehicle arrived early */
  waitingMin: number
  slaViolations: number
  unassignedCount: number
}
