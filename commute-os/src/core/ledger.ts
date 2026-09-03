/**
 * PURPOSE: every rupee and kilogram the UI claims, in one auditable place.
 * PIVOT: if the statement is cost-led, tune the rates here and nothing else;
 *        if it is carbon-led, the co2* factors are the levers.
 * SAFE-TO-DELETE: no — CostModelPanel renders this and judges ask about it.
 */
import type { Fuel, Vehicle } from './types'

export type VehicleClass = 'sedan' | 'suv' | 'shuttle'

/**
 * ALL VALUES ARE TUNABLE ASSUMPTIONS, not MoveInSync actuals.
 * MODEL_BASIS below documents where each number comes from; the UI renders
 * both so "where does that figure come from?" is a click, not a stammer.
 */
export const MODEL = Object.freeze({
  cabRatePerKm: 18,
  cabBaseFarePerTrip: 60,
  suvRatePerKm: 22,
  shuttleRatePerKm: 26,
  shuttleSeats: 12,
  driverCostPerHour: 180,
  metroFarePerTrip: 30,

  co2SedanPerKm: 0.142,
  co2SuvPerKm: 0.186,
  co2ShuttlePerKm: 0.268,
  co2EvPerKm: 0.1,
  co2MetroPerPassengerKm: 0.014,

  /** minutes lost arriving at a new stop, regardless of headcount */
  setupMinPerStop: 1.5,
  /** additional minutes per passenger boarding at that stop */
  serviceMinPerPassenger: 0.5,
})

export const MODEL_BASIS: Record<string, string> = {
  cabRatePerKm: 'vehicle-only running cost; driver billed separately via driverCostPerHour',
  cabBaseFarePerTrip: 'fixed per-dispatch component',
  suvRatePerKm: 'larger body, higher contract rate',
  shuttleRatePerKm: '12-seater; cheaper PER PASSENGER despite higher per-km',
  shuttleSeats: 'standard 12-seat tempo traveller',
  driverCostPerHour: 'fully loaded driver cost',
  metroFarePerTrip: 'BMRCL mid-distance fare',
  co2SedanPerKm: 'petrol sedan ~6.1 L/100km x 2.31 kg CO2/L',
  co2SuvPerKm: 'petrol SUV ~8.0 L/100km x 2.31 kg CO2/L',
  co2ShuttlePerKm: '12-seater diesel ~10 L/100km x 2.68 kg CO2/L',
  co2EvPerKm: '0.14 kWh/km x ~0.71 kg CO2/kWh India grid mix — a ~30% cut, NOT zero',
  co2MetroPerPassengerKm: 'electrified rail at high load factor',
  setupMinPerStop: 'door-to-vehicle time at a new pickup point (FleetPy std_bt)',
  serviceMinPerPassenger: 'marginal boarding time per extra person (FleetPy add_bt)',
}

/** Body class from seat count. */
export function classOf(v: Vehicle): VehicleClass {
  if (v.seats >= MODEL.shuttleSeats) return 'shuttle'
  if (v.seats > 4) return 'suv'
  return 'sedan'
}

function ratePerKm(cls: VehicleClass): number {
  if (cls === 'shuttle') return MODEL.shuttleRatePerKm
  if (cls === 'suv') return MODEL.suvRatePerKm
  return MODEL.cabRatePerKm
}

/** Base fare + distance + driver time. */
export function cabCostInr(km: number, minutes: number, cls: VehicleClass): number {
  return (
    MODEL.cabBaseFarePerTrip +
    km * ratePerKm(cls) +
    (minutes / 60) * MODEL.driverCostPerHour
  )
}

/**
 * Carbon per km. Fuel wins over body class: an EV is an EV whatever its shape.
 * Note the EV figure is ~0.10 vs ~0.14 for petrol — a real cut, not zero.
 */
export function co2KgPerKm(cls: VehicleClass, fuel: Fuel): number {
  if (fuel === 'EV') return MODEL.co2EvPerKm
  if (cls === 'shuttle') return MODEL.co2ShuttlePerKm
  if (cls === 'suv') return MODEL.co2SuvPerKm
  return MODEL.co2SedanPerKm
}

export function co2Kg(km: number, cls: VehicleClass, fuel: Fuel): number {
  return km * co2KgPerKm(cls, fuel)
}

export function metroCostInr(passengers: number): number {
  return passengers * MODEL.metroFarePerTrip
}

export function metroCo2Kg(paxKm: number): number {
  return paxKm * MODEL.co2MetroPerPassengerKm
}

/**
 * Boarding time, split into a per-stop and a per-passenger component.
 * Two colleagues at one gate cost setup + 2*service, NOT 2*(setup + service) —
 * so same-building pooling is genuinely cheaper. (spec 06 §6.4, spec 07 §3)
 */
export function boardingMinutes(stops: number, passengers: number): number {
  return stops * MODEL.setupMinPerStop + passengers * MODEL.serviceMinPerPassenger
}
