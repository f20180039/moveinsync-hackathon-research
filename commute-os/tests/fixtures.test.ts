import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { cacheKey, createRouteProvider, type RouteCache } from '../src/core/routing'
import { computeMetrics } from '../src/core/scenario'
import type { Trip, World } from '../src/core/types'

const need = (p: string): unknown => {
  if (!existsSync(p)) throw new Error(`missing fixture ${p} — run: npm run fixtures`)
  return JSON.parse(readFileSync(p, 'utf8'))
}

const world = need('data/generated/bengaluru.world.json') as World
const trips = need('data/generated/trips.200.json') as Trip[]
const cache = need('data/generated/routes.cache.json') as RouteCache

describe('generated world', () => {
  it('has the six Bengaluru zones', () => {
    expect(world.zones.length).toBe(6)
    expect(world.zones.map((z) => z.name).sort()).toEqual([
      'Bellandur', 'Electronic City', 'HSR Layout', 'Indiranagar', 'Koramangala', 'Whitefield',
    ])
  })

  it('has 4 offices, each with 2 or 3 gates', () => {
    expect(world.offices.length).toBe(4)
    for (const o of world.offices) {
      expect(o.gates.length).toBeGreaterThanOrEqual(2)
      expect(o.gates.length).toBeLessThanOrEqual(3)
    }
    // the 3-gate office exists — gate-spread needs it to have anything to block
    expect(world.offices.some((o) => o.gates.length === 3)).toBe(true)
  })

  it('has 200 employees, 40 vehicles and 25 drivers', () => {
    expect(world.employees.length).toBe(200)
    expect(world.vehicles.length).toBe(40)
    expect(world.drivers.length).toBe(25)
  })

  it('carries the real metro graph: 83 stations, 3 lines, 164 edges', () => {
    expect(world.metroStations.length).toBe(83)
    expect(world.metroLines.length).toBe(3)
    expect(world.metroEdges.length).toBe(164)
  })

  it('includes EVs with a range and a state of charge', () => {
    const evs = world.vehicles.filter((v) => v.fuel === 'EV')
    expect(evs.length).toBeGreaterThan(0)
    for (const ev of evs) {
      expect(ev.rangeKm).toBeGreaterThan(0)
      expect(ev.socPct).toBeGreaterThan(0)
    }
    // a low-charge EV exists — ev-range needs it; socPct > 0 alone would pass at 100%
    expect(world.vehicles.some((v) => v.fuel === 'EV' && (v.socPct ?? 100) < 40)).toBe(true)
  })

  it('includes drivers deliberately near the 12-hour duty cap', () => {
    expect(world.drivers.some((d) => d.dutyMinutesToday > 660)).toBe(true)
  })
})

describe('generated trips', () => {
  it('has exactly 200 trips with unique ids', () => {
    expect(trips.length).toBe(200)
    expect(new Set(trips.map((t) => t.id)).size).toBe(200)
  })

  it('covers both directions', () => {
    expect(trips.some((t) => t.direction === 'login')).toBe(true)
    expect(trips.some((t) => t.direction === 'logout')).toBe(true)
  })

  it('includes a night-shift cohort so gender-safety has something to block', () => {
    const night = trips.filter((t) => t.isNightShift)
    expect(night.length).toBeGreaterThan(10)
    const nightFemaleSolo = night.filter((t) => {
      const people = t.employeeIds.map((id) => world.employees.find((e) => e.id === id))
      return people.length === 1 && people[0]?.gender === 'F'
    })
    expect(nightFemaleSolo.length).toBeGreaterThan(0)
  })

  it('gives every trip at least one window, with start before end', () => {
    for (const t of trips) {
      expect(t.windows.length).toBeGreaterThanOrEqual(1)
      for (const [s, e] of t.windows) expect(s).toBeLessThan(e)
    }
  })

  it('gives some trips two windows — the multi-window case must be exercised', () => {
    expect(trips.some((t) => t.windows.length === 2)).toBe(true)
  })

  it('references only real employees, vehicles, drivers, offices and gates', () => {
    const eids = new Set(world.employees.map((e) => e.id))
    const vids = new Set(world.vehicles.map((v) => v.id))
    const dids = new Set(world.drivers.map((d) => d.id))
    for (const t of trips) {
      for (const e of t.employeeIds) expect(eids.has(e)).toBe(true)
      expect(vids.has(t.vehicleId)).toBe(true)
      expect(dids.has(t.driverId)).toBe(true)
      const office = world.offices.find((o) => o.id === t.officeId)
      expect(office).toBeDefined()
      expect(office!.gates.some((g) => g.id === t.gateId)).toBe(true)
    }
  })
})

describe('generated fixtures produce coherent metrics', () => {
  it('baseline metrics are internally coherent — the floor cannot exceed usage', () => {
    // This is the assertion whose absence let occupancy read 89.29% and a fleet
    // of 40 sit under a floor of 50. It runs computeMetrics over the REAL
    // committed fixtures, not a synthetic world.
    const m = computeMetrics(trips, world, createRouteProvider(cache))
    expect(m.theoreticalFloorVehicles).toBeLessThanOrEqual(m.vehiclesUsed)
    expect(m.avgOccupancyPct).toBeGreaterThan(0)
    expect(m.avgOccupancyPct).toBeLessThan(60) // the premise is half-empty cabs
    expect(m.unassignedCount).toBe(0)
  })

  it('the loose theoretical floor uses the largest vehicle in the fleet as its unit', () => {
    // Derived from the fixture fleet, not pasted, so this keeps holding if the
    // fleet changes. The real 40-vehicle fixture mixes 4/6/12-seat vehicles —
    // pinning to a hard-coded 4-seat unit would overstate this to 50.
    const maxSeats = Math.max(...world.vehicles.map((v) => v.seats))
    const passengers = trips.reduce((a, t) => a + t.seatsUsed, 0)
    const m = computeMetrics(trips, world, createRouteProvider(cache))
    expect(m.theoreticalFloorVehicles).toBe(Math.ceil(passengers / maxSeats))
  })

  it('isNightShift agrees with local (IST) time, in both directions', () => {
    const istHour = (ms: number) =>
      Number(new Date(ms).toLocaleString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', hour12: false }).slice(0, 2))
    for (const t of trips) {
      const h = istHour(t.windows[0]![0])
      expect(h >= 21 || h < 6).toBe(t.isNightShift)
    }
    // and the night cohort must cover BOTH directions, or gender-safety's
    // night-login rule has no fixture coverage at all
    const night = trips.filter((t) => t.isNightShift)
    expect(night.some((t) => t.direction === 'login')).toBe(true)
    expect(night.some((t) => t.direction === 'logout')).toBe(true)
  })
})

describe('generated route cache', () => {
  it('covers every trip pickup -> its office gate, in both directions', () => {
    // The old assertion was `keys.length >= trips.length`, which 828 unrelated
    // zone/feeder keys satisfy on their own — it would have passed with every
    // trip leg missing.
    for (const t of trips) {
      const office = world.offices.find((o) => o.id === t.officeId)!
      const gate = office.gates.find((g) => g.id === t.gateId)!
      expect(cache[cacheKey(t.pickupAt, gate.at)]).toBeDefined()
      expect(cache[cacheKey(gate.at, t.pickupAt)]).toBeDefined()
    }
  })
})

describe('determinism', () => {
  it('is byte-stable — the committed fixtures match their recorded hashes', () => {
    // The previous test asserted trips[0].id === 't000', which is a loop-index
    // fact true of any generator. This pins actual content, so a PRNG-stream
    // shift or an unseeded source produces a red test rather than a silent
    // change caught only by a manual git diff.
    const sha = (f: string) =>
      createHash('sha256').update(readFileSync(`data/generated/${f}`)).digest('hex').slice(0, 16)
    expect(sha('bengaluru.world.json')).toBe('04eea3b5f09b9de8')
    expect(sha('trips.200.json')).toBe('b27dcceb40f842dc')
    expect(sha('routes.cache.json')).toBe('231e5caf8b6d522c')
  })
})
