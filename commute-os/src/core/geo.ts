/**
 * PURPOSE: geodesic distance, road-distance estimation, and zone containment.
 * PIVOT: if the statement needs real road distance everywhere, raise ROAD_FACTOR
 *        or move callers onto routing.ts's cache; this file stays the fallback.
 * SAFE-TO-DELETE: no — geo is used by every solver and half the policies.
 *
 * Geodesy and polygon containment are @turf/* (MIT). We own only the coordinate
 * adapter and the road factor — see docs/REUSE-AUDIT.md.
 */
import { distance } from '@turf/distance'
import { booleanPointInPolygon } from '@turf/boolean-point-in-polygon'
import { point, polygon as turfPolygon } from '@turf/helpers'
import type { LatLng, Zone } from './types'

/**
 * Multiplier from great-circle to driving distance. Design §6.2 / spec 01 §7:
 * used whenever the route cache misses, so the demo never depends on a network
 * call. 1.3 is the conventional urban figure.
 */
export const ROAD_FACTOR = 1.3

/**
 * THE ONLY PLACE the two coordinate conventions meet. turf and GeoJSON are
 * [lng, lat]; our domain is { lat, lng }. Reversing this produces distances
 * that look plausible and are wrong, so it lives here and nowhere else.
 */
const toPos = (p: LatLng): [number, number] => [p.lng, p.lat]

/** Great-circle distance in kilometres (turf's haversine, R = 6371008.8 m). */
export function haversineKm(a: LatLng, b: LatLng): number {
  return distance(point(toPos(a)), point(toPos(b)), { units: 'kilometers' })
}

/** Road-distance estimate: great-circle inflated by ROAD_FACTOR. */
export function estimateKm(a: LatLng, b: LatLng): number {
  return haversineKm(a, b) * ROAD_FACTOR
}

/**
 * Zone.polygon is stored as an OPEN ring (the first vertex is not repeated),
 * but GeoJSON requires a closed one and turf THROWS
 * "First and last Position are not equivalent" if it is open. Close it here so
 * no caller has to know. A ring of fewer than 3 vertices is rejected before
 * turf sees it, since that also throws.
 */
export function pointInZone(p: LatLng, z: Zone): boolean {
  if (z.polygon.length < 3) return false
  const ring = z.polygon.map(toPos)
  const first = ring[0]!
  const closed: Array<[number, number]> = [...ring, [first[0], first[1]]]
  return booleanPointInPolygon(point(toPos(p)), turfPolygon([closed]))
}

/**
 * The `n` items closest to `p` within `maxKm`, nearest first.
 * Used for metro boarding/alighting candidate search (design §10.1).
 */
export function nearestN<T extends { at: LatLng }>(
  p: LatLng,
  items: T[],
  n: number,
  maxKm: number,
): T[] {
  return items
    .map((item) => ({ item, km: haversineKm(p, item.at) }))
    .filter((x) => x.km <= maxKm)
    .sort((a, b) => a.km - b.km)
    .slice(0, n)
    .map((x) => x.item)
}
