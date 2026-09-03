/**
 * PURPOSE: a merge may not push a driver past the legal duty ceiling.
 * PIVOT: real compliance needs scheduled breaks with max_load (VROOM, spec 06
 *        §4) — Tier C. This is the cumulative ceiling only.
 * SAFE-TO-DELETE: no — labour compliance is a question judges ask.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const MAX_DUTY_MIN = 720  // 12 hours
export const WARN_DUTY_MIN = 660 // 11 hours

export const driverHours: Policy = (c, w) => {
  const id = 'driver-hours'
  const name = 'Driver hours'
  const driver = w.drivers.find((d) => d.id === c.driverId)
  if (!driver) {
    return verdict(id, name, 'block', 'max_travel_time', `Unknown driver ${c.driverId}`)
  }

  const total = driver.dutyMinutesToday + c.minutes
  const spare = MAX_DUTY_MIN - total

  if (spare < 0) {
    return verdict(id, name, 'block', 'max_travel_time',
      `${driver.name} would reach ${total.toFixed(0)} min of duty, ${MAX_DUTY_MIN} allowed`,
      { value: spare, unit: 'min' })
  }
  if (total > WARN_DUTY_MIN) {
    return verdict(id, name, 'soft', 'max_travel_time',
      `${driver.name} nearing the duty cap at ${total.toFixed(0)} min`,
      { value: spare, unit: 'min' })
  }
  return pass(id, name, `${driver.name} at ${total.toFixed(0)}/${MAX_DUTY_MIN} min`,
    { value: spare, unit: 'min' })
}
