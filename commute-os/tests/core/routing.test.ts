import { describe, it, expect } from 'vitest'
import { cacheKey, createRouteProvider, AVG_CITY_SPEED_KMPH } from '../../src/core/routing'
import { estimateKm } from '../../src/core/geo'
import type { RouteCache } from '../../src/core/routing'

const A = { lat: 12.9352, lng: 77.6245 } // Koramangala
const B = { lat: 12.9260, lng: 77.6762 } // Bellandur-ish

describe('cacheKey', () => {
  it('is stable and direction-sensitive', () => {
    expect(cacheKey(A, B)).toBe(cacheKey({ ...A }, { ...B }))
    expect(cacheKey(A, B)).not.toBe(cacheKey(B, A))
  })

  it('rounds to 4 decimals so near-identical points share a key', () => {
    expect(cacheKey(A, B)).toBe(cacheKey({ lat: 12.93521, lng: 77.62449 }, B))
  })
})

describe('createRouteProvider', () => {
  const cache: RouteCache = {
    [cacheKey(A, B)]: { km: 7.4, minutes: 21, polyline: [A, { lat: 12.93, lng: 77.65 }, B] },
  }

  it('returns the cached route tagged source=cache', () => {
    const r = createRouteProvider(cache).route(A, B)
    expect(r.km).toBe(7.4)
    expect(r.minutes).toBe(21)
    expect(r.polyline.length).toBe(3)
    expect(r.source).toBe('cache')
  })

  it('falls back to a straight-line estimate tagged source=estimate', () => {
    const r = createRouteProvider(cache).route(B, A) // reverse key is absent
    expect(r.source).toBe('estimate')
    expect(r.km).toBeCloseTo(estimateKm(B, A), 9)
    expect(r.polyline).toEqual([B, A])
  })

  it('derives estimate minutes from the documented city speed', () => {
    const r = createRouteProvider({}).route(A, B)
    expect(r.minutes).toBeCloseTo((estimateKm(A, B) / AVG_CITY_SPEED_KMPH) * 60, 6)
    expect(AVG_CITY_SPEED_KMPH).toBe(22)
  })

  it('applies the traffic multiplier to minutes but never to distance', () => {
    const plain = createRouteProvider(cache).route(A, B)
    const heavy = createRouteProvider(cache, 1.5).route(A, B)
    expect(heavy.minutes).toBeCloseTo(plain.minutes * 1.5, 6)
    expect(heavy.km).toBe(plain.km)
  })

  it('returns zero for identical points without consulting the cache', () => {
    const r = createRouteProvider({}).route(A, A)
    expect(r.km).toBe(0)
    expect(r.minutes).toBe(0)
    expect(r.source).toBe('estimate')
  })
})
