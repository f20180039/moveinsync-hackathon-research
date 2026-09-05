import { label } from '../api/labels.ts'
import type { Tier } from '../api/types.ts'

// Breach and Concern are the only saturated tiers on screen (a strong
// fill, white/dark text) -- Watch and Pass are deliberately desaturated
// (an outline badge, a thin stripe), so the eye lands on red/amber first.
const STRONG_TIERS = new Set<Tier>(['BREACH', 'CONCERN'])

// One glyph per tier -- filled for the two that need attention (a warning
// triangle, a circled exclamation), outline for the two that don't (an
// eye for "keep watching", a check for "on its reference"). Severity in
// form as well as colour: the shape carries meaning even in greyscale.
function TierIcon({ tier }: { tier: Tier }) {
  switch (tier) {
    case 'BREACH':
      return (
        <svg className="tier-badge__icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M8 1.5 15 14.5H1Z" fill="currentColor" />
          <rect x="7.25" y="5.5" width="1.5" height="4.5" fill="var(--bg)" />
          <rect x="7.25" y="11" width="1.5" height="1.5" fill="var(--bg)" />
        </svg>
      )
    case 'CONCERN':
      return (
        <svg className="tier-badge__icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="7" fill="currentColor" />
          <rect x="7.25" y="4" width="1.5" height="5" fill="var(--bg)" />
          <rect x="7.25" y="10.5" width="1.5" height="1.5" fill="var(--bg)" />
        </svg>
      )
    case 'WATCH':
      return (
        <svg className="tier-badge__icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path
            d="M1 8s3-5 7-5 7 5 7 5-3 5-7 5-7-5-7-5Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
          />
          <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
        </svg>
      )
    case 'PASS':
      return (
        <svg className="tier-badge__icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path
            d="M3 8.5 6 11.5 13 4.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
  }
}

export function TierBadge({ tier }: { tier: Tier }) {
  const strong = STRONG_TIERS.has(tier)
  const classes = [
    'tier-badge',
    `tier-badge--${tier.toLowerCase()}`,
    strong ? 'tier-badge--strong' : 'tier-badge--muted',
  ].join(' ')

  return (
    <span className={classes}>
      <span aria-hidden="true" className="tier-badge__stripe" />
      <TierIcon tier={tier} />
      <strong className="tier-badge__word">{label('tier', tier)}</strong>
    </span>
  )
}
