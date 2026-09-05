import { useId, useState } from 'react'
import { Button } from './Button.tsx'
import { TierBadge } from './TierBadge.tsx'

const STORAGE_KEY = 'signal-desk:legend-collapsed'

// localStorage can throw (private browsing, storage disabled, a full quota)
// -- every read/write is guarded so a first-time visitor's render never
// depends on it succeeding. Open (not collapsed) is the safe default in
// every failure case: a new user should see the legend, not lose it to a
// storage quirk.
function readStoredCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function writeStoredCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(collapsed))
  } catch {
    // Nothing to do -- the collapse state just won't survive a reload.
  }
}

// "How to read this" -- open by default for a first-time visitor, collapsed
// state remembered after that. Placed between the header and the control
// strip so it's the first thing a new user reads, and out of the way for
// everyone after.
export function Legend() {
  const [collapsed, setCollapsed] = useState(readStoredCollapsed)
  const panelId = useId()

  function toggle() {
    setCollapsed((value) => {
      const next = !value
      writeStoredCollapsed(next)
      return next
    })
  }

  return (
    <section className="legend" aria-label="How to read this">
      <div className="legend__header">
        <h2 className="legend__title">How to read this</h2>
        <Button variant="ghost" size="sm" aria-expanded={!collapsed} aria-controls={panelId} onClick={toggle}>
          {collapsed ? 'Show' : 'Hide'}
        </Button>
      </div>

      {!collapsed && (
        <div id={panelId} className="legend__body">
          <div className="legend__section">
            <h3>Severity</h3>
            <ul className="legend__tiers">
              <li>
                <TierBadge tier="PASS" /> <span>on its reference</span>
              </li>
              <li>
                <TierBadge tier="WATCH" /> <span>small drift — keep an eye</span>
              </li>
              <li>
                <TierBadge tier="CONCERN" /> <span>clear shortfall — act this week</span>
              </li>
              <li>
                <TierBadge tier="BREACH" />{' '}
                <span>serious — act now; goes to the facilities head too</span>
              </li>
            </ul>
          </div>

          <div className="legend__section">
            <h3>Compared against</h3>
            <p>
              4-week average = this slice's own last four weeks · peer median = the other
              vendors/sites/etc. in the same week · target = a contractual/hard target when one
              exists
            </p>
          </div>

          <div className="legend__section">
            <h3>Confidence</h3>
            <p>
              shown only when below 0.9 — it means part of the underlying feed was quarantined or
              unmatched
            </p>
          </div>

          <div className="legend__section">
            <h3>Evidence</h3>
            <p>expand any row → the exact SQL that produced the number; runnable as-is</p>
          </div>

          <div className="legend__section">
            <h3>Feed health</h3>
            <ul>
              <li>Quarantined = rows the sweep rejected outright</li>
              <li>Unmatched = rows that couldn't be joined to their key</li>
              <li>Confidence = share of this feed's rows we trust</li>
            </ul>
          </div>

          <div className="legend__section">
            <h3>Cost</h3>
            <p>one model call per brief; ₹ figures are approximate (±17%)</p>
          </div>
        </div>
      )}
    </section>
  )
}
