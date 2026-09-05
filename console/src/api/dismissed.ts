// Dismissed-finding tracking for the priority-action cards. localStorage,
// guarded -- a dismissal that can't persist (private browsing, storage
// disabled) still hides the card for the rest of this render, it just
// won't survive a reload.
//
// Keyed by finding id only, deliberately. A finding's id is a stable hash
// of (metric | slice dimension | value | window) by design -- so the same
// underlying shortfall (same metric, same slice, same window) keeps the
// same id across a re-sweep, and dismissing it legitimately stays
// dismissed if the operator re-sweeps the same window. It does NOT carry
// forward to a different window: next week's finding for the same
// metric/slice hashes to a different id (the window is part of the hash),
// so it starts undismissed. This is intentional, not a gap -- there is no
// separate "window" key to store here.
const DISMISS_STORAGE_KEY = 'signal-desk:dismissed-findings'

function readDismissedIds(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISS_STORAGE_KEY)
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set()
  } catch {
    return new Set()
  }
}

function persistDismissedIds(ids: Set<string>): void {
  try {
    localStorage.setItem(DISMISS_STORAGE_KEY, JSON.stringify(Array.from(ids)))
  } catch {
    // Nothing to do -- the dismissal just won't survive a reload.
  }
}

export function isDismissed(findingId: string): boolean {
  return readDismissedIds().has(findingId)
}

export function markDismissed(findingId: string): void {
  const dismissed = readDismissedIds()
  dismissed.add(findingId)
  persistDismissedIds(dismissed)
}
