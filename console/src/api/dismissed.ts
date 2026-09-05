// Dismissed-finding tracking for the priority-action cards. localStorage,
// guarded -- a dismissal that can't persist (private browsing, storage
// disabled) still hides the card for the rest of this render, it just
// won't survive a reload.

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
