/**
 * PURPOSE: run every policy over a candidate and return a complete, tiered trace.
 * PIVOT: adding rule eleven is one file in policies/ plus one array entry in
 *        policies/index.ts. Nothing here changes.
 * SAFE-TO-DELETE: no — this is the moat; the UI renders its output verbatim.
 */
import type {
  Candidate, Policy, PolicyCtx, PolicyStatus, PolicyTrace, PolicyVerdict,
  ViolationCause, World,
} from './types'

/**
 * Ascending severity. Compared lexicographically and NEVER summed: with a
 * single score, dropping a trip and driving further become commensurable, and
 * the solver learns to look efficient by serving fewer people.
 * (spec 08 §2 HardMediumSoftScore; spec 07 §5 assignment_reward.)
 */
export const TIER_ORDER = ['pass', 'soft', 'medium', 'block'] as const

export function tierRank(s: PolicyStatus): number {
  return TIER_ORDER.indexOf(s)
}

/** Negative if `a` is more acceptable than `b`. */
export function compareTiers(a: PolicyStatus, b: PolicyStatus): number {
  return tierRank(a) - tierRank(b)
}

export function worstTier(verdicts: PolicyVerdict[]): PolicyStatus {
  let worst: PolicyStatus = 'pass'
  for (const v of verdicts) if (tierRank(v.status) > tierRank(worst)) worst = v.status
  return worst
}

export function pass(
  id: string, name: string, reason: string,
  slack?: { value: number; unit: string },
): PolicyVerdict {
  return slack === undefined
    ? { id, name, status: 'pass', reason }
    : { id, name, status: 'pass', reason, slack }
}

export function verdict(
  id: string, name: string, status: PolicyStatus, cause: ViolationCause,
  reason: string, slack?: { value: number; unit: string },
): PolicyVerdict {
  return slack === undefined
    ? { id, name, status, cause, reason }
    : { id, name, status, cause, reason, slack }
}

/**
 * Evaluates ALL policies, including those after a block. A partial trace would
 * defeat the point: an admin needs to see every reason a merge failed, not just
 * the first, and the UI shows blocked proposals rather than hiding them.
 */
export function evaluate(
  policies: Policy[], c: Candidate, w: World, ctx: PolicyCtx,
): PolicyTrace {
  const verdicts = policies.map((p) => p(c, w, ctx))
  return {
    verdicts,
    blocked: verdicts.some((v) => v.status === 'block'),
    tier: worstTier(verdicts),
  }
}
