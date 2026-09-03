/**
 * PURPOSE: the shared contract every solver strategy (merge, feeder, ...)
 *          implements — input shape, proposal shape, result shape.
 * PIVOT: adding a solver-level concept (e.g. a new proposal kind or a solver
 *        diagnostic field) starts here, before any individual solver.
 * SAFE-TO-DELETE: no — every solver and the orchestration layer imports this.
 */
import type { Metrics, Policy, PolicyTrace, RouteSource, Savings, Trip, World, LatLng } from '../core/types'
import type { RouteProvider } from '../core/routing'

export type SolverInput = {
  world: World
  trips: Trip[]
  policies: Policy[]
  /** simulation time, epoch ms — NEVER read from the system clock */
  now: number
  /** solver-specific tuning knobs, e.g. a max-detour-minutes slider */
  params?: Record<string, number>
}

/** A single suggested (or already judged) grouping, ready for the UI. */
export type Proposal = {
  id: string
  kind: 'merge' | 'feeder'
  tripIds: string[]
  geometry: LatLng[]
  routeSource: RouteSource
  /** complete even when blocked — the UI shows refusals too */
  trace: PolicyTrace
  savings: Savings
  explanation?: string
  status: 'suggested' | 'approved' | 'rejected'
}

export type SolverResult = {
  proposals: Proposal[]
  baseline: Metrics
  solved: Metrics
  diff: Metrics
}

/**
 * `run` must be pure: it may not mutate `i` (SolverInput). Every solver
 * routes through the same `RouteProvider`, so results stay comparable and
 * offline-deterministic.
 */
export type Solver = {
  id: string
  name: string
  run(i: SolverInput, rp: RouteProvider): SolverResult
}
