/**
 * PURPOSE: resolve a route between two points, offline and deterministically.
 * PIVOT: a live API tier (ORS/Google) belongs here and NOWHERE else — but it is
 *        Tier C (spec §19) and deliberately not built. The cache is the demo.
 * SAFE-TO-DELETE: no — solvers and scenario metrics both route through this.
 */
import type { LatLng, RouteResult } from './types'
import { estimateKm } from './geo'

/** Bengaluru peak average. Used only for the estimate tier. */
export const AVG_CITY_SPEED_KMPH = 22

export type RouteCache = Record<string, { km: number; minutes: number; polyline: LatLng[] }>

const r4 = (n: number): string => n.toFixed(4)

/** Direction-sensitive key, rounded so near-identical points share an entry. */
export function cacheKey(a: LatLng, b: LatLng): string {
  return `${r4(a.lat)},${r4(a.lng)}|${r4(b.lat)},${r4(b.lng)}`
}

export type RouteProvider = { route(a: LatLng, b: LatLng): RouteResult }

/**
 * cache -> straight-line x ROAD_FACTOR. `source` is surfaced in the UI so an
 * estimated leg renders as a dotted line labelled "Estimated route"
 * (design §14). Traffic scales time only, never distance.
 */
export function createRouteProvider(cache: RouteCache, trafficMultiplier = 1): RouteProvider {
  return {
    route(a: LatLng, b: LatLng): RouteResult {
      if (a.lat === b.lat && a.lng === b.lng) {
        return { km: 0, minutes: 0, polyline: [a], source: 'estimate' }
      }
      const hit = cache[cacheKey(a, b)]
      if (hit) {
        return {
          km: hit.km,
          minutes: hit.minutes * trafficMultiplier,
          polyline: hit.polyline,
          source: 'cache',
        }
      }
      const km = estimateKm(a, b)
      return {
        km,
        minutes: (km / AVG_CITY_SPEED_KMPH) * 60 * trafficMultiplier,
        polyline: [a, b],
        source: 'estimate',
      }
    },
  }
}
