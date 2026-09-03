/**
 * PURPOSE: a lone female employee is never pooled or last-dropped at night.
 * PIVOT: if the statement is safety-led, promote this to the hero policy and
 *        add escort assignment + route-deviation alerts (Tier B).
 * SAFE-TO-DELETE: no. This is a hard block and the most memorable demo beat —
 *                 a system that refuses is more credible than one that never does.
 */
import type { Employee, Policy, Trip } from '../types'
import { pass, verdict } from '../policy'

export const NIGHT_START_HOUR = 21
export const NIGHT_END_HOUR = 6

function employeesOf(trips: Trip[], all: Employee[]): Employee[] {
  const ids = new Set(trips.flatMap((t) => t.employeeIds))
  return all.filter((e) => ids.has(e.id))
}

export const genderSafety: Policy = (c, w) => {
  const id = 'gender-safety'
  const name = 'Gender safety'

  // Scope everything to the NIGHT-FLAGGED trips. Counting the whole candidate
  // lets a female riding a DAY leg shield a lone female on the night leg — she
  // is not in the vehicle during the risk window, so she cannot chaperone it.
  const nightTrips = c.trips.filter((t) => t.isNightShift)
  if (nightTrips.length === 0) return pass(id, name, 'Daytime trip — no night-shift restriction')

  const people = employeesOf(nightTrips, w.employees)

  // A safety rule that cannot identify its passengers must refuse, not assume.
  // Every other policy fails closed on an unresolvable referent; this is the one
  // where failing open is least acceptable.
  if (people.length === 0) {
    return verdict(id, name, 'block', 'skills',
      `Safety policy: cannot resolve any passenger on a night-shift merge — ` +
      `refusing rather than assuming it is safe`)
  }

  const females = people.filter((e) => e.gender === 'F')

  if (females.length === 1) {
    return verdict(id, name, 'block', 'skills',
      `Safety policy: lone female (${females[0]!.name}) on a night-shift merge. ` +
      `Requires a second female passenger or a dedicated escort.`)
  }

  // Last-drop rule: on a night logout the final passenger must not be a lone female.
  const logouts = c.trips.filter((t) => t.direction === 'logout' && t.isNightShift)
  if (logouts.length > 0) {
    const last = logouts[logouts.length - 1]!
    const lastPeople = employeesOf([last], w.employees)
    const lastFemales = lastPeople.filter((e) => e.gender === 'F')
    if (lastPeople.length > 0 && lastFemales.length === lastPeople.length) {
      return verdict(id, name, 'block', 'skills',
        `Safety policy: ${lastFemales.map((e) => e.name).join(', ')} would be the ` +
        `last drop on a night logout. Reorder the route or assign an escort.`)
    }
  }

  return females.length === 0
    ? pass(id, name, 'No female passengers on this night merge')
    : pass(id, name, `${females.length} female passengers — night merge permitted`)
}
