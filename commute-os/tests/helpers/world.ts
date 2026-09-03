import type { Candidate, PolicyCtx, Trip, World } from '../../src/core/types'

/** Fixed epoch ms — 2026-09-04T09:00:00Z-ish. Never Date.now(). */
export const T0 = 1_757_000_000_000
const MIN = 60_000

export function makeTrip(over: Partial<Trip> = {}): Trip {
  return {
    id: 't1',
    employeeIds: ['e1'],
    pickupAt: { lat: 12.9352, lng: 77.6245 },
    zoneId: 'z-koramangala',
    officeId: 'o1',
    gateId: 'g1',
    direction: 'login',
    windows: [[T0, T0 + 30 * MIN]],
    seatsUsed: 1,
    vehicleId: 'v-sedan',
    driverId: 'd-fresh',
    isNightShift: false,
    ...over,
  }
}

export function makeWorld(over: Partial<World> = {}): World {
  return {
    zones: [{
      id: 'z-koramangala', name: 'Koramangala',
      centroid: { lat: 12.9352, lng: 77.6245 },
      polygon: [
        { lat: 12.91, lng: 77.60 }, { lat: 12.91, lng: 77.65 },
        { lat: 12.96, lng: 77.65 }, { lat: 12.96, lng: 77.60 },
      ],
      confidence: 1,
    }],
    offices: [{
      id: 'o1', name: 'Office One', at: { lat: 12.9260, lng: 77.6762 },
      gates: [
        { id: 'g1', name: 'Gate 1', at: { lat: 12.9260, lng: 77.6762 } },
        { id: 'g2', name: 'Gate 2', at: { lat: 12.9268, lng: 77.6790 } },
        { id: 'g3', name: 'Gate 3', at: { lat: 12.9280, lng: 77.6830 } },
      ],
    }],
    employees: [
      { id: 'e1', name: 'Asha', gender: 'F', homeAt: { lat: 12.9352, lng: 77.6245 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.05 },
      { id: 'e2', name: 'Bhavna', gender: 'F', homeAt: { lat: 12.9360, lng: 77.6260 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.10 },
      { id: 'e3', name: 'Chandran', gender: 'M', homeAt: { lat: 12.9370, lng: 77.6270 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.20 },
      { id: 'e4', name: 'Dinesh', gender: 'M', homeAt: { lat: 12.9380, lng: 77.6280 }, zoneId: 'z-koramangala', officeId: 'o1', noShowRate: 0.02 },
    ],
    vehicles: [
      { id: 'v-sedan', plate: 'KA01AA0001', seats: 4, fuel: 'ICE' },
      { id: 'v-ev', plate: 'KA01AA0002', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 100 },
      { id: 'v-ev-low', plate: 'KA01AA0003', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 30 },
      { id: 'v-shuttle', plate: 'KA01AA0004', seats: 12, fuel: 'CNG' },
    ],
    drivers: [
      { id: 'd-fresh', name: 'Ramesh', dutyMinutesToday: 60, score: 90 },
      { id: 'd-near-cap', name: 'Suresh', dutyMinutesToday: 700, score: 80 },
      { id: 'd-warn', name: 'Girish', dutyMinutesToday: 670, score: 85 },
    ],
    depots: [{ id: 'dep1', name: 'Depot One', at: { lat: 12.94, lng: 77.62 } }],
    metroLines: [], metroStations: [], metroEdges: [],
    ...over,
  }
}

export function makeCandidate(over: Partial<Candidate> = {}): Candidate {
  const trips = over.trips ?? [makeTrip()]
  return {
    tripIds: trips.map((t) => t.id),
    trips,
    vehicleId: 'v-sedan',
    driverId: 'd-fresh',
    km: 8,
    minutes: 24,
    perPassengerAddedMin: {},
    gateIds: ['g1'],
    seatsUsed: trips.reduce((a, t) => a + t.seatsUsed, 0),
    pickupTimes: Object.fromEntries(trips.map((t) => [t.id, t.windows[0]![0]])),
    ...over,
  }
}

export function makeCtx(over: Partial<PolicyCtx> = {}): PolicyCtx {
  return { now: T0, zoneRejections: {}, trafficMultiplier: 1, detourMinutesThisWeek: {}, ...over }
}
