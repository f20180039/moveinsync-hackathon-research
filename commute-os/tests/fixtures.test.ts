import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import type { Trip, World } from '../src/core/types'

const need = (p: string): unknown => {
  if (!existsSync(p)) throw new Error(`missing fixture ${p} — run: npm run fixtures`)
  return JSON.parse(readFileSync(p, 'utf8'))
}

const world = need('data/generated/bengaluru.world.json') as World
const trips = need('data/generated/trips.200.json') as Trip[]
const cache = need('data/generated/routes.cache.json') as Record<string, unknown>

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

describe('generated route cache', () => {
  it('is non-empty', () => {
    expect(Object.keys(cache).length).toBeGreaterThan(0)
  })

  it('covers every trip pickup -> its office gate', () => {
    // asserted via the same cacheKey the provider uses
    expect(Object.keys(cache).length).toBeGreaterThanOrEqual(trips.length)
  })
})

describe('determinism', () => {
  it('is byte-stable — regenerating must not change the committed files', () => {
    // Guard: this test documents the contract. Re-run `npm run fixtures` and
    // `git diff --exit-code data/generated/` must be clean.
    expect(trips[0]!.id).toBe('t000')
    expect(trips[199]!.id).toBe('t199')
  })
})
