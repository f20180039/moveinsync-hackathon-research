import { describe, it, expect } from 'vitest'
import {
  MODEL, MODEL_BASIS, classOf, cabCostInr, co2KgPerKm, co2Kg,
  metroCostInr, metroCo2Kg, boardingMinutes,
} from '../../src/core/ledger'
import type { Vehicle } from '../../src/core/types'

const sedan: Vehicle = { id: 'v1', plate: 'KA01AA0001', seats: 4, fuel: 'ICE' }
const ev: Vehicle = { id: 'v2', plate: 'KA01AA0002', seats: 4, fuel: 'EV', rangeKm: 150, socPct: 90 }
const suv: Vehicle = { id: 'v3', plate: 'KA01AA0003', seats: 6, fuel: 'ICE' }
const shuttle: Vehicle = { id: 'v4', plate: 'KA01AA0004', seats: 12, fuel: 'CNG' }

describe('MODEL', () => {
  it('holds the design §6.4 rates', () => {
    expect(MODEL.cabRatePerKm).toBe(18)
    expect(MODEL.cabBaseFarePerTrip).toBe(60)
    expect(MODEL.suvRatePerKm).toBe(22)
    expect(MODEL.shuttleRatePerKm).toBe(26)
    expect(MODEL.driverCostPerHour).toBe(180)
    expect(MODEL.metroFarePerTrip).toBe(30)
  })

  it('holds the design §6.4 carbon factors', () => {
    expect(MODEL.co2SedanPerKm).toBe(0.142)
    expect(MODEL.co2SuvPerKm).toBe(0.186)
    expect(MODEL.co2ShuttlePerKm).toBe(0.268)
    expect(MODEL.co2EvPerKm).toBe(0.1)
    expect(MODEL.co2MetroPerPassengerKm).toBe(0.014)
  })

  it('documents a basis string for every numeric constant', () => {
    const numericKeys = Object.keys(MODEL).filter((k) => typeof (MODEL as Record<string, unknown>)[k] === 'number')
    const undocumented = numericKeys.filter((k) => !MODEL_BASIS[k])
    expect(undocumented).toEqual([])
  })

  it('is frozen so no caller can mutate the demo economics', () => {
    expect(Object.isFrozen(MODEL)).toBe(true)
  })
})

describe('classOf', () => {
  it('classifies by seat count', () => {
    expect(classOf(sedan)).toBe('sedan')
    expect(classOf(suv)).toBe('suv')
    expect(classOf(shuttle)).toBe('shuttle')
    expect(classOf(ev)).toBe('sedan')   // 4 seats — fuel is irrelevant to class
  })
})

describe('cabCostInr', () => {
  it('is base fare plus distance plus driver time for a sedan', () => {
    // 60 + 10*18 + (30/60)*180 = 60 + 180 + 90 = 330
    expect(cabCostInr(10, 30, 'sedan')).toBeCloseTo(330, 6)
  })

  it('charges the shuttle rate for a shuttle', () => {
    // 60 + 10*26 + (30/60)*180 = 60 + 260 + 90 = 410
    expect(cabCostInr(10, 30, 'shuttle')).toBeCloseTo(410, 6)
  })

  it('charges the SUV rate for an SUV', () => {
    // 60 + 10*22 + (30/60)*180 = 60 + 220 + 90 = 370
    expect(cabCostInr(10, 30, 'suv')).toBeCloseTo(370, 6)
  })

  it('still charges the base fare for a zero-distance trip', () => {
    expect(cabCostInr(0, 0, 'sedan')).toBe(MODEL.cabBaseFarePerTrip)
  })
})

describe('co2KgPerKm', () => {
  it('uses the EV factor regardless of body class', () => {
    expect(co2KgPerKm('sedan', 'EV')).toBe(0.1)
    expect(co2KgPerKm('suv', 'EV')).toBe(0.1)
  })

  it('uses body class for combustion vehicles', () => {
    expect(co2KgPerKm('sedan', 'ICE')).toBe(0.142)
    expect(co2KgPerKm('suv', 'ICE')).toBe(0.186)
    expect(co2KgPerKm('shuttle', 'CNG')).toBe(0.268)
  })

  it('shows an EV is cleaner than petrol but NOT zero — the honesty check', () => {
    expect(co2KgPerKm('sedan', 'EV')).toBeLessThan(co2KgPerKm('sedan', 'ICE'))
    expect(co2KgPerKm('sedan', 'EV')).toBeGreaterThan(0)
  })
})

describe('co2Kg and metro', () => {
  it('scales carbon linearly with distance', () => {
    expect(co2Kg(10, 'sedan', 'ICE')).toBeCloseTo(1.42, 6)
    expect(co2Kg(5, 'suv', 'ICE')).toBeCloseTo(0.93, 6)
  })

  it('prices metro per passenger', () => {
    expect(metroCostInr(3)).toBe(90)
  })

  it('makes metro dramatically cleaner per passenger-km than a cab', () => {
    expect(metroCo2Kg(10)).toBeCloseTo(0.14, 6)
    expect(metroCo2Kg(10)).toBeLessThan(co2Kg(10, 'sedan', 'EV'))
  })
})

describe('boardingMinutes', () => {
  it('charges setup once per stop and service once per passenger', () => {
    // 2 stops, 3 passengers = 2*1.5 + 3*0.5 = 4.5
    expect(boardingMinutes(2, 3)).toBeCloseTo(4.5, 6)
  })

  it('makes two colleagues at ONE gate cheaper than at two gates', () => {
    expect(boardingMinutes(1, 2)).toBeLessThan(boardingMinutes(2, 2))
  })

  it('is zero for an empty candidate', () => {
    expect(boardingMinutes(0, 0)).toBe(0)
  })
})
