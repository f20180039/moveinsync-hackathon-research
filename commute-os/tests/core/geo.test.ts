import { describe, it, expect } from 'vitest'
import { haversineKm, estimateKm, pointInZone, nearestN, ROAD_FACTOR } from '../../src/core/geo'
import type { Zone } from '../../src/core/types'

// Real Bengaluru landmarks from the CC0 metro dataset (spec 04).
const MAJESTIC = { lat: 12.97559, lng: 77.57313 }
const MG_ROAD = { lat: 12.97566, lng: 77.60676 }
const WHITEFIELD = { lat: 12.99570, lng: 77.75773 }
const ELECTRONIC_CITY = { lat: 12.85654, lng: 77.66328 }

describe('haversineKm', () => {
  it('is zero for identical points', () => {
    expect(haversineKm(MAJESTIC, MAJESTIC)).toBe(0)
  })

  it('matches the known Majestic -> MG Road distance (3.644 km)', () => {
    expect(haversineKm(MAJESTIC, MG_ROAD)).toBeCloseTo(3.644, 2)
  })

  it('matches the known Majestic -> Whitefield distance (20.13 km)', () => {
    expect(haversineKm(MAJESTIC, WHITEFIELD)).toBeCloseTo(20.13, 1)
  })

  it('is symmetric', () => {
    expect(haversineKm(MAJESTIC, ELECTRONIC_CITY)).toBeCloseTo(
      haversineKm(ELECTRONIC_CITY, MAJESTIC), 9)
  })

  it('handles one degree of latitude as ~111 km', () => {
    expect(haversineKm({ lat: 12, lng: 77 }, { lat: 13, lng: 77 })).toBeCloseTo(111.195, 2)
  })
})

describe('estimateKm', () => {
  it('applies the road factor to the great-circle distance', () => {
    expect(estimateKm(MAJESTIC, MG_ROAD)).toBeCloseTo(haversineKm(MAJESTIC, MG_ROAD) * ROAD_FACTOR, 9)
  })

  it('uses a road factor of 1.3', () => {
    expect(ROAD_FACTOR).toBe(1.3)
  })
})

describe('turf integration guards', () => {
  it('does not silently swap lat and lng', () => {
    // If toPos were reversed, this Bengaluru pair would land in the Indian
    // Ocean and the distance would be wildly different.
    expect(haversineKm(MAJESTIC, MG_ROAD)).toBeLessThan(10)
  })

  it('does not throw on an open ring — geo.ts closes it', () => {
    const openSquare: Zone = {
      id: 'z2', name: 'Open', centroid: { lat: 12.95, lng: 77.62 },
      polygon: [
        { lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 },
        { lat: 13.00, lng: 77.67 }, { lat: 13.00, lng: 77.57 },
      ],
      confidence: 1,
    }
    expect(() => pointInZone({ lat: 12.95, lng: 77.62 }, openSquare)).not.toThrow()
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, openSquare)).toBe(true)
  })

  it('does not throw on a 2-point degenerate ring', () => {
    const bad: Zone = {
      id: 'z3', name: 'Bad', centroid: { lat: 12.95, lng: 77.62 },
      polygon: [{ lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 }],
      confidence: 1,
    }
    expect(() => pointInZone({ lat: 12.95, lng: 77.62 }, bad)).not.toThrow()
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, bad)).toBe(false)
  })
})

describe('pointInZone', () => {
  // a 0.1 x 0.1 degree square around Koramangala-ish
  const square: Zone = {
    id: 'z1', name: 'Square', centroid: { lat: 12.95, lng: 77.62 },
    polygon: [
      { lat: 12.90, lng: 77.57 }, { lat: 12.90, lng: 77.67 },
      { lat: 13.00, lng: 77.67 }, { lat: 13.00, lng: 77.57 },
    ],
    confidence: 1,
  }

  it('accepts an interior point', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, square)).toBe(true)
  })

  it('rejects a point outside to the east', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.90 }, square)).toBe(false)
  })

  it('rejects a point outside to the south', () => {
    expect(pointInZone({ lat: 12.50, lng: 77.62 }, square)).toBe(false)
  })

  it('rejects a degenerate polygon with fewer than 3 points', () => {
    expect(pointInZone({ lat: 12.95, lng: 77.62 }, { ...square, polygon: [] })).toBe(false)
  })
})

describe('nearestN', () => {
  const items = [
    { id: 'mg', at: MG_ROAD },
    { id: 'wf', at: WHITEFIELD },
    { id: 'ec', at: ELECTRONIC_CITY },
  ]

  it('returns the closest items in ascending distance order', () => {
    expect(nearestN(MAJESTIC, items, 3, 100).map((i) => i.id)).toEqual(['mg', 'ec', 'wf'])
  })

  it('respects the count limit', () => {
    expect(nearestN(MAJESTIC, items, 1, 100).map((i) => i.id)).toEqual(['mg'])
  })

  it('excludes items beyond maxKm', () => {
    expect(nearestN(MAJESTIC, items, 3, 5).map((i) => i.id)).toEqual(['mg'])
  })

  it('returns an empty array when nothing is in range', () => {
    expect(nearestN(MAJESTIC, items, 3, 0.001)).toEqual([])
  })
})
