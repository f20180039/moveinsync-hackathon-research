import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'
import { Button } from './Button.tsx'
import { TierBadge } from './TierBadge.tsx'

const STORAGE_KEY = 'signal-desk:legend-seen'

// localStorage can throw (private browsing, storage disabled, a full quota)
// -- every read/write is guarded so a first-time visitor's render never
// depends on it succeeding. "Not seen" is the safe default in every failure
// case: a new user should see the legend, not lose it to a storage quirk.
function readHasBeenSeen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function markSeen(): void {
  try {
    localStorage.setItem(STORAGE_KEY, 'true')
  } catch {
    // Nothing to do -- it just reopens automatically next visit.
  }
}

// "How to read this" as a modal dialog, opened from a header button. Opens
// automatically on a genuine first visit and never again once the visitor
// has closed it once (tracked in localStorage), closes on Escape, a
// backdrop click, or the Close button, and returns focus to the trigger
// that opened it. Nothing on the page shifts when it opens: the dialog is
// fixed-positioned as an overlay regardless of whether the browser's native
// showModal() is available.
//
// `<dialog>.showModal()`/`.close()` are unsupported in some test
// environments (notably jsdom as of this writing) -- every call is feature-
// detected, falling back to toggling the `open` attribute directly, so the
// component behaves the same (if slightly less automatically) wherever it
// runs.
export function Legend() {
  const [open, setOpen] = useState(false)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()

  // Stable identity ([] deps -- only refs and setState, both stable) so it
  // can sit in the mount effect's dependency array without the effect
  // re-firing on every `open` change. Unguarded by design: at mount `open`
  // is always false, so there's nothing to guard against yet.
  const showDialog = useCallback(() => {
    const dialogEl = dialogRef.current
    if (dialogEl) {
      if (typeof dialogEl.showModal === 'function') {
        dialogEl.showModal()
      } else {
        dialogEl.setAttribute('open', '')
        dialogEl.focus()
      }
    }
    setOpen(true)
  }, [])

  useEffect(() => {
    if (!readHasBeenSeen()) {
      // This *is* the "should the legend open" check itself -- there is no
      // render-time value to derive it from, it depends on localStorage.
      // oxlint-disable-next-line react/set-state-in-effect
      showDialog()
    }
  }, [showDialog])

  // Guarded wrapper for the trigger button -- calling showModal() on an
  // already-open <dialog> throws in real browsers, so user-initiated opens
  // (unlike the one mount-time check above) need the guard.
  function openDialog() {
    if (open) return
    showDialog()
  }

  function closeDialog() {
    if (!open) return
    const dialogEl = dialogRef.current
    if (dialogEl) {
      if (typeof dialogEl.close === 'function') {
        dialogEl.close()
      } else {
        dialogEl.removeAttribute('open')
      }
    }
    setOpen(false)
    markSeen()
    triggerRef.current?.focus()
  }

  function handleBackdropClick(event: MouseEvent<HTMLDialogElement>) {
    // A click directly on the <dialog> element itself (not on the panel
    // inside it) is a click on the backdrop -- whether that's the real
    // ::backdrop pseudo-element (native showModal) or just the dialog's own
    // padding around the panel (the non-modal fallback).
    if (event.target === dialogRef.current) {
      closeDialog()
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeDialog()
    }
  }

  return (
    <>
      <Button ref={triggerRef} variant="ghost" size="sm" onClick={openDialog}>
        How to read this
      </Button>
      <dialog
        ref={dialogRef}
        className="legend-dialog"
        tabIndex={-1}
        aria-labelledby={titleId}
        onClick={handleBackdropClick}
        onKeyDown={handleKeyDown}
      >
        <div className="legend-dialog__panel">
          <div className="legend-dialog__header">
            <h2 id={titleId} className="legend-dialog__title">
              How to read this
            </h2>
            <Button variant="ghost" size="sm" onClick={closeDialog}>
              Close
            </Button>
          </div>

          <div className="legend__body">
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
        </div>
      </dialog>
    </>
  )
}
