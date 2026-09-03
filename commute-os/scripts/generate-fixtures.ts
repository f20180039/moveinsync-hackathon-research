/**
 * PURPOSE: generate the deterministic Bengaluru fixture set.
 * PIVOT: tuning the demo is tuning THIS FILE — zone mix, night cohort size,
 *        EV share, driver duty spread. Re-run `npm run fixtures` and commit.
 * SAFE-TO-DELETE: no — the committed JSON is generated, not hand-edited.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import seedrandom from 'seedrandom'
import { fakerEN_IN as faker } from '@faker-js/faker'
import { buildMetroGraph, parseMetroCsv } from '../src/core/metro'
import { AVG_CITY_SPEED_KMPH, cacheKey } from '../src/core/routing'
import { estimateKm, haversineKm } from '../src/core/geo'
import type {
  Driver, Employee, Gate, LatLng, Office, Trip, Vehicle, World, Zone, Window,
} from '../src/core/types'

/** Fixed seed = the hackathon date. Never change it casually. */
export const SEED = 20260905

/**
 * seedrandom (MIT, zero deps) rather than a hand-rolled PRNG, and faker's
 * Indian-English locale for names. Both are seeded, so regeneration is
 * byte-stable — proven by the git diff --exit-code step below.
 */
const rnd = seedrandom(String(SEED))
faker.seed(SEED)
const pick = <T,>(xs: T[]): T => xs[Math.floor(rnd() * xs.length)]!
const jitter = (v: number, spread: number): number => v + (rnd() - 0.5) * 2 * spread
const MIN = 60_000
/** Demo day starts 2026-09-05T00:00:00Z. */
const DAY0 = Date.UTC(2026, 8, 5, 0, 0, 0)
const at = (h: number, m = 0): number => DAY0 + h * 60 * MIN + m * MIN

// ── zones ───────────────────────────────────────────────────────────────────
const ZONE_SEEDS: Array<{ name: string; at: LatLng }> = [
  { name: 'Koramangala', at: { lat: 12.9352, lng: 77.6245 } },
  { name: 'Bellandur', at: { lat: 12.9260, lng: 77.6762 } },
  { name: 'Indiranagar', at: { lat: 12.9784, lng: 77.6408 } },
  { name: 'Whitefield', at: { lat: 12.9698, lng: 77.7500 } },
  { name: 'Electronic City', at: { lat: 12.8452, lng: 77.6602 } },
  { name: 'HSR Layout', at: { lat: 12.9116, lng: 77.6474 } },
]

const zones: Zone[] = ZONE_SEEDS.map((z, i) => {
  const d = 0.022
  return {
    id: `z${i}`,
    name: z.name,
    centroid: z.at,
    polygon: [
      { lat: z.at.lat - d, lng: z.at.lng - d },
      { lat: z.at.lat - d, lng: z.at.lng + d },
      { lat: z.at.lat + d, lng: z.at.lng + d },
      { lat: z.at.lat + d, lng: z.at.lng - d },
    ],
    confidence: 1,
  }
})

// ── offices ─────────────────────────────────────────────────────────────────
const OFFICE_SEEDS: Array<{ name: string; at: LatLng; gates: number }> = [
  { name: 'Ecospace Bellandur', at: { lat: 12.9256, lng: 77.6810 }, gates: 3 },
  { name: 'Embassy Tech Village', at: { lat: 12.9330, lng: 77.6890 }, gates: 3 },
  { name: 'ITPL Whitefield', at: { lat: 12.9855, lng: 77.7368 }, gates: 2 },
  { name: 'Infosys Electronic City', at: { lat: 12.8480, lng: 77.6630 }, gates: 2 },
]

const offices: Office[] = OFFICE_SEEDS.map((o, i) => {
  const gates: Gate[] = Array.from({ length: o.gates }, (_, g) => ({
    id: `o${i}g${g}`,
    name: `Gate ${g + 1}`,
    at: { lat: jitter(o.at.lat, 0.004), lng: jitter(o.at.lng, 0.004) },
  }))
  return { id: `o${i}`, name: o.name, at: o.at, gates }
})

// ── employees ───────────────────────────────────────────────────────────────
const employees: Employee[] = Array.from({ length: 200 }, (_, i) => {
  const z = zones[i % zones.length]!
  // ~42% female, deterministic BY INDEX rather than random, so the night cohort
  // (i % 9 === 0, below) reliably contains lone-female trips for the safety
  // demo. Leaving this to the PRNG would make the demo's best beat a lottery.
  const gender: Employee['gender'] = i % 12 < 5 ? 'F' : 'M'
  const firstName = faker.person.firstName(gender === 'F' ? 'female' : 'male')
  return {
    id: `e${String(i).padStart(3, '0')}`,
    name: `${firstName} ${faker.person.lastName()}`,
    gender,
    homeAt: { lat: jitter(z.centroid.lat, 0.018), lng: jitter(z.centroid.lng, 0.018) },
    zoneId: z.id,
    officeId: offices[i % offices.length]!.id,
    noShowRate: Math.round((0.02 + rnd() * 0.23) * 100) / 100,
  }
})

// ── fleet ───────────────────────────────────────────────────────────────────
const vehicles: Vehicle[] = Array.from({ length: 40 }, (_, i) => {
  if (i < 10) {
    // EVs, including several deliberately low on charge for the range demo
    const soc = i < 3 ? 25 + i * 5 : 70 + ((i * 7) % 30)
    return { id: `v${i}`, plate: `KA01EV${1000 + i}`, seats: 4, fuel: 'EV' as const,
      rangeKm: 150, socPct: soc }
  }
  if (i < 16) return { id: `v${i}`, plate: `KA01CN${1000 + i}`, seats: 12, fuel: 'CNG' as const }
  if (i < 24) return { id: `v${i}`, plate: `KA01SU${1000 + i}`, seats: 6, fuel: 'ICE' as const }
  return { id: `v${i}`, plate: `KA01SD${1000 + i}`, seats: 4, fuel: 'ICE' as const }
})

const drivers: Driver[] = Array.from({ length: 25 }, (_, i) => ({
  id: `d${i}`,
  name: `Driver ${i + 1}`,
  // 3 drivers deliberately over the 660-minute warn line, 1 over the cap
  dutyMinutesToday: i === 0 ? 700 : i < 4 ? 670 : Math.floor(rnd() * 400),
  score: 60 + Math.floor(rnd() * 40),
}))

// ── metro (real CC0 data) ───────────────────────────────────────────────────
const csv = readFileSync('data/bengaluru_metro_network.csv', 'utf8')
const graph = buildMetroGraph(parseMetroCsv(csv))

const world: World = {
  zones, offices, employees, vehicles, drivers,
  depots: [
    { id: 'dep0', name: 'Bellandur Depot', at: { lat: 12.9210, lng: 77.6700 } },
    { id: 'dep1', name: 'Whitefield Depot', at: { lat: 12.9800, lng: 77.7300 } },
  ],
  metroLines: graph.lines,
  metroStations: graph.stations,
  metroEdges: graph.edges,
}

// ── trips ───────────────────────────────────────────────────────────────────
const trips: Trip[] = Array.from({ length: 200 }, (_, i) => {
  const emp = employees[i]!
  const office = offices.find((o) => o.id === emp.officeId)!
  const isNight = i % 9 === 0                       // ~22 night trips
  const direction: Trip['direction'] = i % 3 === 0 ? 'logout' : 'login'
  const baseHour = isNight ? (direction === 'login' ? 22 : 5) : direction === 'login' ? 8 : 18
  const start = at(baseHour, (i * 7) % 55)

  // ~15% of trips get a second acceptable window (the multi-window case)
  const windows: Window[] = i % 7 === 3
    ? [[start, start + 20 * MIN], [start + 60 * MIN, start + 85 * MIN]]
    : [[start, start + 30 * MIN]]

  return {
    id: `t${String(i).padStart(3, '0')}`,
    employeeIds: [emp.id],
    pickupAt: emp.homeAt,
    zoneId: emp.zoneId,
    officeId: office.id,
    gateId: pick(office.gates).id,
    direction,
    windows,
    seatsUsed: 1,
    vehicleId: vehicles[i % vehicles.length]!.id,
    driverId: drivers[i % drivers.length]!.id,
    isNightShift: isNight,
  }
})

// ── route cache: every pickup -> its gate, plus zone-centroid pairs ─────────
const cache: Record<string, { km: number; minutes: number; polyline: LatLng[] }> = {}
const addLeg = (a: LatLng, b: LatLng): void => {
  const key = cacheKey(a, b)
  if (cache[key]) return
  const km = estimateKm(a, b)
  cache[key] = {
    km: Math.round(km * 1000) / 1000,
    minutes: Math.round((km / AVG_CITY_SPEED_KMPH) * 60 * 100) / 100,
    polyline: [a, { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 }, b],
  }
}

for (const t of trips) {
  const office = offices.find((o) => o.id === t.officeId)!
  const gate = office.gates.find((g) => g.id === t.gateId)!
  addLeg(t.pickupAt, gate.at)
  addLeg(gate.at, t.pickupAt)
}
// pickup-to-pickup legs within a zone, so the merger can chain without estimating
for (const z of zones) {
  const inZone = trips.filter((t) => t.zoneId === z.id).slice(0, 12)
  for (const a of inZone) for (const b of inZone) if (a.id !== b.id) addLeg(a.pickupAt, b.pickupAt)
}
// feeder legs: every zone centroid to its nearest 3 metro stations
for (const z of zones) {
  const near = [...graph.stations]
    .map((s) => ({ s, km: haversineKm(z.centroid, s.at) }))
    .sort((x, y) => x.km - y.km).slice(0, 3)
  for (const { s } of near) { addLeg(z.centroid, s.at); addLeg(s.at, z.centroid) }
}

// ── write ───────────────────────────────────────────────────────────────────
mkdirSync('data/generated', { recursive: true })
const write = (name: string, data: unknown): void => {
  writeFileSync(`data/generated/${name}`, `${JSON.stringify(data, null, 2)}\n`)
  console.log(`  wrote data/generated/${name}`)
}
write('bengaluru.world.json', world)
write('trips.200.json', trips)
write('routes.cache.json', cache)
console.log(`  seed=${SEED}  zones=${zones.length} offices=${offices.length} ` +
  `employees=${employees.length} trips=${trips.length} cacheKeys=${Object.keys(cache).length}`)
