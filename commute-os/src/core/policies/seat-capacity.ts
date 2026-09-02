/**
 * PURPOSE: a merge may not exceed the assigned vehicle's seat count.
 * PIVOT: for luggage or wheelchair dimensions, make this a vector check
 *        (spec 05 §3.1) — currently Tier C, seats only.
 * SAFE-TO-DELETE: no — the most basic feasibility rule.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const seatCapacity: Policy = (c, w) => {
  const id = 'seat-capacity'
  const name = 'Seat capacity'
  const vehicle = w.vehicles.find((v) => v.id === c.vehicleId)
  if (!vehicle) {
    return verdict(id, name, 'block', 'load', `Unknown vehicle ${c.vehicleId}`)
  }
  const spare = vehicle.seats - c.seatsUsed
  return spare >= 0
    ? pass(id, name, `${c.seatsUsed}/${vehicle.seats} seats used`, { value: spare, unit: 'seats' })
    : verdict(id, name, 'block', 'load',
        `${c.seatsUsed} passengers exceeds ${vehicle.seats} seats`,
        { value: spare, unit: 'seats' })
}
