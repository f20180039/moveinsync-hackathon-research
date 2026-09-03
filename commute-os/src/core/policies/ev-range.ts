/**
 * PURPOSE: an EV may not be assigned a route beyond its usable range.
 * PIVOT: if the statement is EV/green-led, pair this with a charging scheduler
 *        (FleetPy charging/Threshold, spec 07 §6) — Tier B.
 * SAFE-TO-DELETE: no — MoveInSync runs ~500 EVs; this is a real constraint.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Fraction of usable charge held back as reserve. */
export const EV_RESERVE_FRACTION = 0.2

export const evRange: Policy = (c, w) => {
  const id = 'ev-range'
  const name = 'EV range'
  const vehicle = w.vehicles.find((v) => v.id === c.vehicleId)
  if (!vehicle) {
    return verdict(id, name, 'block', 'max_distance', `Unknown vehicle ${c.vehicleId}`)
  }
  if (vehicle.fuel !== 'EV') {
    return pass(id, name, `${vehicle.plate} is not an EV — range is unconstrained`)
  }

  const nameplate = vehicle.rangeKm ?? 0
  const socFraction = (vehicle.socPct ?? 100) / 100
  const usableKm = nameplate * socFraction * (1 - EV_RESERVE_FRACTION)
  const spare = usableKm - c.km

  return spare >= 0
    ? pass(id, name, `${c.km.toFixed(1)} km of ${usableKm.toFixed(1)} km usable`,
        { value: spare, unit: 'km' })
    : verdict(id, name, 'block', 'max_distance',
        `${c.km.toFixed(1)} km exceeds ${usableKm.toFixed(1)} km usable — reassign to CNG or ICE`,
        { value: spare, unit: 'km' })
}
