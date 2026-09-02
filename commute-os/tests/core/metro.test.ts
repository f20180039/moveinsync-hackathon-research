import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  parseMetroCsv, buildMetroGraph, toMetroGraph, findMetroPath, metroLegMinutes,
  AVG_METRO_SPEED_KMPH, DWELL_MIN_PER_STOP, INTERCHANGE_MIN,
} from '../../src/core/metro'
import type { MetroCsvRow } from '../../src/core/metro'

const CSV = readFileSync('data/bengaluru_metro_network.csv', 'utf8')
const rows = parseMetroCsv(CSV)
const graph = buildMetroGraph(rows)
const mg = toMetroGraph(graph.edges) // built once; findMetroPath takes the graph

describe('parseMetroCsv', () => {
  it('parses all 85 data rows', () => {
    expect(rows.length).toBe(85)
  })

  it('parses the first Purple Line row exactly', () => {
    const whtm = rows.find((r) => r.station_code === 'WHTM')
    expect(whtm).toBeDefined()
    expect(whtm!.station_name).toBe('Whitefield (Kadugodi)')
    expect(whtm!.line).toBe('Purple Line')
    expect(whtm!.sequence).toBe(1)
    expect(whtm!.next_station_code).toBe('UWVL')
    expect(whtm!.distance_to_next_km).toBeCloseTo(1.04, 6)
    expect(whtm!.latitude).toBeCloseTo(12.995699, 5)
    expect(whtm!.line_color).toBe('#7E22CE')
    expect(whtm!.is_interchange).toBe(false)
  })

  it('reads terminals as having no next station', () => {
    const terminals = rows.filter((r) => r.next_station_code === null)
    expect(terminals.map((r) => r.station_code).sort()).toEqual(['APTS', 'CHLG', 'DELT'])
  })
})

// ── GOTCHA 2: 85 rows, 83 stations ────────────────────────────────────────
describe('buildMetroGraph — station de-duplication', () => {
  it('collapses 85 rows into 83 unique stations', () => {
    expect(graph.stations.length).toBe(83)
  })

  it('gives the two interchanges BOTH their line memberships', () => {
    const kgwa = graph.stations.find((s) => s.id === 'KGWA')
    const rvr = graph.stations.find((s) => s.id === 'RVR')
    expect(kgwa!.lineIds.sort()).toEqual(['Green Line', 'Purple Line'])
    expect(rvr!.lineIds.sort()).toEqual(['Green Line', 'Yellow Line'])
  })

  it('marks exactly two stations as interchanges', () => {
    const ic = graph.stations.filter((s) => s.isInterchange).map((s) => s.id).sort()
    expect(ic).toEqual(['KGWA', 'RVR'])
  })

  it('gives every other station exactly one line', () => {
    const multi = graph.stations.filter((s) => s.lineIds.length > 1).map((s) => s.id).sort()
    expect(multi).toEqual(['KGWA', 'RVR'])
  })
})

describe('buildMetroGraph — lines', () => {
  it('builds three lines with the documented station counts', () => {
    const byId = Object.fromEntries(graph.lines.map((l) => [l.id, l]))
    expect(byId['Purple Line']!.stationIds.length).toBe(37)
    expect(byId['Green Line']!.stationIds.length).toBe(32)
    expect(byId['Yellow Line']!.stationIds.length).toBe(16)
  })

  it('orders each line by sequence', () => {
    const yellow = graph.lines.find((l) => l.id === 'Yellow Line')!
    expect(yellow.stationIds[0]).toBe('RVR')
    expect(yellow.stationIds[yellow.stationIds.length - 1]).toBe('DELT')
  })

  it('carries the line colour', () => {
    expect(graph.lines.find((l) => l.id === 'Yellow Line')!.colour).toBe('#CA8A04')
  })
})

// ── GOTCHA 1 & 3: directed source, terminal sentinels ─────────────────────
describe('buildMetroGraph — edges', () => {
  it('emits 164 edges: 82 forward hops, both directions', () => {
    // 85 rows - 3 terminals = 82 forward; x2 = 164
    expect(graph.edges.length).toBe(164)
  })

  it('synthesises the REVERSE edge for every forward edge', () => {
    const fwd = graph.edges.find((e) => e.from === 'WHTM' && e.to === 'UWVL')
    const rev = graph.edges.find((e) => e.from === 'UWVL' && e.to === 'WHTM')
    expect(fwd!.km).toBeCloseTo(1.04, 6)
    expect(rev!.km).toBeCloseTo(1.04, 6)
  })

  it('never emits a zero-km edge from a terminal sentinel', () => {
    expect(graph.edges.filter((e) => e.km === 0)).toEqual([])
    for (const t of ['CHLG', 'APTS', 'DELT']) {
      // a terminal still has an inbound-derived reverse edge, but no edge
      // created FROM its own null next_station_code
      expect(graph.edges.filter((e) => e.from === t && e.km === 0)).toEqual([])
    }
  })
})

describe('findMetroPath', () => {
  it('returns a zero-length path for the same station', () => {
    const p = findMetroPath('RVR', 'RVR', mg)
    expect(p).toEqual({ stationIds: ['RVR'], km: 0, interchanges: 0 })
  })

  it('finds the 3-hop Yellow Line path RVR -> BTM Layout at 3.16 km', () => {
    const p = findMetroPath('RVR', 'BTML', mg)!
    expect(p.stationIds).toEqual(['RVR', 'RAGI', 'JDEV', 'BTML'])
    expect(p.km).toBeCloseTo(3.16, 2)
    expect(p.interchanges).toBe(0)
  })

  it('travels the reverse direction too — proving gotcha 1 is handled', () => {
    const p = findMetroPath('BTML', 'RVR', mg)!
    expect(p.stationIds).toEqual(['BTML', 'JDEV', 'RAGI', 'RVR'])
    expect(p.km).toBeCloseTo(3.16, 2)
  })

  it('routes across an interchange and counts it', () => {
    // Whitefield (Purple) -> Electronic City (Yellow) must change lines twice:
    // Purple -> Green at KGWA, Green -> Yellow at RVR
    const p = findMetroPath('WHTM', 'ELCT', mg)!
    expect(p.stationIds[0]).toBe('WHTM')
    expect(p.stationIds[p.stationIds.length - 1]).toBe('ELCT')
    expect(p.stationIds).toContain('KGWA')
    expect(p.stationIds).toContain('RVR')
    expect(p.interchanges).toBe(2)
    expect(p.km).toBeGreaterThan(30)
  })

  it('returns null for an unknown station', () => {
    expect(findMetroPath('RVR', 'NOPE', mg)).toBeNull()
    expect(findMetroPath('NOPE', 'RVR', mg)).toBeNull()
  })
})

describe('metroLegMinutes', () => {
  it('is travel time + dwell + interchange penalty', () => {
    const p = { stationIds: ['RVR', 'RAGI', 'JDEV', 'BTML'], km: 3.16, interchanges: 0 }
    // 3.16/32*60 = 5.925 ; dwell 4*0.35 = 1.4 ; headway/2 excluded by default
    expect(metroLegMinutes(p)).toBeCloseTo(7.325, 3)
  })

  it('adds the interchange penalty', () => {
    const p = { stationIds: ['A', 'B'], km: 3.16, interchanges: 2 }
    const base = { ...p, interchanges: 0 }
    expect(metroLegMinutes(p) - metroLegMinutes(base)).toBeCloseTo(2 * INTERCHANGE_MIN, 6)
  })

  it('adds half the headway as expected wait when one is supplied', () => {
    const p = { stationIds: ['A', 'B'], km: 1, interchanges: 0 }
    expect(metroLegMinutes(p, 6) - metroLegMinutes(p)).toBeCloseTo(3, 6)
  })

  it('uses the documented constants', () => {
    expect(AVG_METRO_SPEED_KMPH).toBe(32)
    expect(DWELL_MIN_PER_STOP).toBe(0.35)
    expect(INTERCHANGE_MIN).toBe(5)
  })
})

describe('buildMetroGraph — trap 3 isolated from trap 1', () => {
  it('drops a zero-distance hop even when next_station_code is a real station', () => {
    // The real CSV never contains this row shape: distance 0 with a real next
    // station. Without it, the zero-distance guard is unreachable and untested,
    // because every zero-distance row is also a terminal.
    const mk = (code: string, next: string | null, km: number): MetroCsvRow => ({
      station_code: code, station_name: code, line: 'Test Line', sequence: 1,
      is_interchange: false, next_station_code: next,
      latitude: 12.9, longitude: 77.6, distance_to_next_km: km, line_color: '#000000',
    })
    const g = buildMetroGraph([mk('A', 'B', 0), mk('B', 'C', 1.5), mk('C', null, 0)])

    // A->B: real next station, zero distance => no edge in EITHER direction
    expect(g.edges.filter((e) => e.from === 'A' || e.to === 'A')).toEqual([])
    // B<->C: valid hop => both directions emitted
    expect(g.edges).toHaveLength(2)
    // and the stations themselves are still all registered
    expect(g.stations.map((s) => s.id).sort()).toEqual(['A', 'B', 'C'])
  })
})
