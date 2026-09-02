/**
 * PURPOSE: turn the CC0 metro CSV into a routable, de-duplicated graph.
 * PIVOT: if the statement is mass-transit led, this file and metro-feeder are
 *        the hero path; new lines are new CSV rows, no code change.
 * SAFE-TO-DELETE: no — Metro Feeder Mesh cannot run without it.
 */
import Graph from 'graphology'
import { dijkstra } from 'graphology-shortest-path'
import Papa from 'papaparse'
import type { MetroEdge, MetroLine, MetroStation } from './types'

/** BMRCL scheduled average including dwell. Estimate — label it in the UI. */
export const AVG_METRO_SPEED_KMPH = 32
/** ~20 s per stop. Estimate. */
export const DWELL_MIN_PER_STOP = 0.35
/** Platform change at Majestic or RV Road. Estimate. */
export const INTERCHANGE_MIN = 5
/** Peak headway; expected wait is half this. Estimate. */
export const DEFAULT_HEADWAY_MIN = 6

export type MetroCsvRow = {
  station_code: string
  station_name: string
  line: string
  sequence: number
  is_interchange: boolean
  /** null at the three terminals */
  next_station_code: string | null
  latitude: number
  longitude: number
  /** 0 at terminals — a SENTINEL, not an edge weight */
  distance_to_next_km: number
  line_color: string
}

/**
 * Parsed with papaparse rather than split(',') — the current file is unquoted,
 * but a hand parser breaks silently the day a station name contains a comma.
 * papaparse yields `""` for an empty field, which is how the three terminals'
 * missing next_station_code arrives; it is mapped to null here.
 */
export function parseMetroCsv(csv: string): MetroCsvRow[] {
  const parsed = Papa.parse<Record<string, string>>(csv, {
    header: true,
    skipEmptyLines: true,
    transform: (v) => v.trim(),
  })
  if (parsed.errors.length > 0) {
    throw new Error(`metro CSV parse error: ${parsed.errors[0]!.message}`)
  }
  return parsed.data.map((r) => {
    const next = r['next_station_code'] ?? ''
    return {
      station_code: r['station_code'] ?? '',
      station_name: r['station_name'] ?? '',
      line: r['line'] ?? '',
      sequence: Number(r['sequence']),
      is_interchange: r['is_interchange'] === '1',
      next_station_code: next === '' || next.toUpperCase() === 'NULL' ? null : next,
      latitude: Number(r['latitude']),
      longitude: Number(r['longitude']),
      distance_to_next_km: Number(r['distance_to_next_km']),
      line_color: r['line_color'] ?? '',
    }
  })
}

/**
 * Build stations, lines and edges.
 *
 * GOTCHA 2: de-duplicate on station_code, ACCUMULATING lineIds — interchanges
 *   appear once per line with coordinates ~50 m apart. First row wins for
 *   coordinates; both lines are recorded.
 * GOTCHA 1: the CSV is directed, so emit BOTH directions for every hop.
 * GOTCHA 3: a null next_station_code means no edge. Never trust the 0.0 km.
 */
export function buildMetroGraph(rows: MetroCsvRow[]): {
  stations: MetroStation[]
  lines: MetroLine[]
  edges: MetroEdge[]
} {
  const stations = new Map<string, MetroStation>()
  const lineRows = new Map<string, MetroCsvRow[]>()
  const edges: MetroEdge[] = []

  for (const r of rows) {
    // ── stations (gotcha 2) ──
    const existing = stations.get(r.station_code)
    if (existing) {
      if (!existing.lineIds.includes(r.line)) existing.lineIds.push(r.line)
      existing.isInterchange = existing.isInterchange || r.is_interchange
    } else {
      stations.set(r.station_code, {
        id: r.station_code,
        name: r.station_name,
        at: { lat: r.latitude, lng: r.longitude },
        lineIds: [r.line],
        isInterchange: r.is_interchange,
      })
    }

    // ── lines ──
    const bucket = lineRows.get(r.line)
    if (bucket) bucket.push(r)
    else lineRows.set(r.line, [r])

    // ── edges (gotchas 1 and 3) ──
    if (r.next_station_code === null) continue
    if (r.distance_to_next_km <= 0) continue
    edges.push({ from: r.station_code, to: r.next_station_code, km: r.distance_to_next_km, lineId: r.line })
    edges.push({ from: r.next_station_code, to: r.station_code, km: r.distance_to_next_km, lineId: r.line })
  }

  const lines: MetroLine[] = [...lineRows.entries()].map(([id, rs]) => {
    const ordered = [...rs].sort((a, b) => a.sequence - b.sequence)
    return {
      id,
      name: id,
      colour: ordered[0]!.line_color,
      stationIds: ordered.map((r) => r.station_code),
      headwayMin: DEFAULT_HEADWAY_MIN,
    }
  })

  return { stations: [...stations.values()], lines, edges }
}

export type MetroGraph = Graph
export type MetroPath = { stationIds: string[]; km: number; interchanges: number }

/**
 * Build the graphology graph once. Undirected and simple: buildMetroGraph
 * already emitted both directions, and no two adjacent stations are joined by
 * more than one line, so mergeEdge cannot lose a parallel edge.
 */
export function toMetroGraph(edges: MetroEdge[]): MetroGraph {
  const g: Graph = new Graph({ type: 'undirected', multi: false })
  for (const e of edges) {
    g.mergeNode(e.from)
    g.mergeNode(e.to)
    g.mergeEdge(e.from, e.to, { km: e.km, lineId: e.lineId })
  }
  return g
}

/**
 * Shortest path by kilometres, via graphology's Dijkstra (a real binary heap —
 * the hand-rolled version this replaced re-sorted its queue every iteration).
 *
 * Two library behaviours must be handled, both verified against
 * graphology-shortest-path 2.1.0:
 *   - `dijkstra.bidirectional` THROWS on a node that is not in the graph, so
 *     guard with hasNode first;
 *   - it returns `null` (not `[]`) when the nodes exist but are disconnected.
 */
export function findMetroPath(fromId: string, toId: string, g: MetroGraph): MetroPath | null {
  if (!g.hasNode(fromId) || !g.hasNode(toId)) return null
  if (fromId === toId) return { stationIds: [fromId], km: 0, interchanges: 0 }

  const path = dijkstra.bidirectional(g, fromId, toId, 'km')
  if (!path || path.length === 0) return null

  let km = 0
  let interchanges = 0
  let prevLine: string | null = null

  for (let i = 0; i < path.length - 1; i++) {
    const edgeKey = g.edge(path[i]!, path[i + 1]!)
    if (edgeKey === undefined) return null
    km += g.getEdgeAttribute(edgeKey, 'km') as number
    const lineId = g.getEdgeAttribute(edgeKey, 'lineId') as string
    if (prevLine !== null && lineId !== prevLine) interchanges++
    prevLine = lineId
  }

  return { stationIds: path, km, interchanges }
}

/**
 * Minutes for a metro leg from REAL inter-station distances — replacing the
 * v1.0 "2.2 min per stop" guess (spec 04 §4).
 * `headwayMin` adds the expected wait (half the headway) when supplied.
 */
export function metroLegMinutes(path: MetroPath, headwayMin?: number): number {
  const travel = (path.km / AVG_METRO_SPEED_KMPH) * 60
  const dwell = path.stationIds.length * DWELL_MIN_PER_STOP
  const change = path.interchanges * INTERCHANGE_MIN
  const wait = headwayMin === undefined ? 0 : headwayMin / 2
  return travel + dwell + change + wait
}
