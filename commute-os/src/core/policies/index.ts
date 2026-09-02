/**
 * PURPOSE: the policy registry. Order here is the order the trace renders in.
 * PIVOT: rule eleven is one import and one array entry. Nothing else changes.
 * SAFE-TO-DELETE: no.
 */
import type { Policy } from '../types'

import { seatCapacity } from './seat-capacity'
import { timeWindow } from './time-window'
import { detourSla } from './detour-sla'
import { gateSpread } from './gate-spread'
import { driverHours } from './driver-hours'
import { evRange } from './ev-range'
import { genderSafety } from './gender-safety'
import { zoneConfidence } from './zone-confidence'
import { noShowRisk } from './no-show-risk'
import { detourFairness } from './detour-fairness'

/** Hard feasibility first, then safety, then the soft preferences. */
export const ALL_POLICIES: Policy[] = [
  seatCapacity,
  timeWindow,
  detourSla,
  gateSpread,
  driverHours,
  evRange,
  genderSafety,
  zoneConfidence,
  noShowRisk,
  detourFairness,
]

export {
  seatCapacity, timeWindow, detourSla, gateSpread, driverHours,
  evRange, genderSafety, zoneConfidence, noShowRisk, detourFairness,
}
