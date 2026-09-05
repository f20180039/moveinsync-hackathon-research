import { label } from '../api/labels.ts'
import type { Tier } from '../api/types.ts'

// Tier order used for styling and legends -- worst first. Colours come from
// the shared tokens in :root (App.css) -- one definition, everywhere a tier
// colour is needed (this stripe, the feed-health flag, the confidence note).
const TIER_STRIPE: Record<Tier, string> = {
  BREACH: 'var(--tier-breach)',
  CONCERN: 'var(--tier-concern)',
  WATCH: 'var(--tier-watch)',
  PASS: 'var(--tier-pass)',
}

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span className="tier-badge">
      <span
        aria-hidden="true"
        className="tier-badge__stripe"
        style={{ background: TIER_STRIPE[tier] }}
      />
      <strong className="tier-badge__word">{label('tier', tier)}</strong>
    </span>
  )
}
