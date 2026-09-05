import type { Tier } from '../api/types.ts'

// Tier order used for styling and legends -- worst first.
const TIER_STRIPE: Record<Tier, string> = {
  BREACH: '#b3261e',
  CONCERN: '#a15c00',
  WATCH: '#5b5bd6',
  PASS: '#1e7a45',
}

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span className="tier-badge">
      <span
        aria-hidden="true"
        className="tier-badge__stripe"
        style={{ background: TIER_STRIPE[tier] }}
      />
      <strong className="tier-badge__word">{tier}</strong>
    </span>
  )
}
