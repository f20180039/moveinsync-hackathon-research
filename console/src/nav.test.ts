import { describe, expect, it } from 'vitest'
import { MAIN_ITEMS, REPORT_ITEMS, titleFor } from './nav.ts'

describe('titleFor', () => {
  it('resolves every nav item to its own label', () => {
    for (const item of [...MAIN_ITEMS, ...REPORT_ITEMS]) {
      expect(titleFor(item.to)).toBe(item.label)
    }
  })

  it('resolves a nested route to its section, not to Overview', () => {
    expect(titleFor('/vendors/VENDOR_12')).toBe('Vendors')
    expect(titleFor('/reports/weekly')).toBe('Weekly review')
  })

  it('matches / exactly, since it prefixes every other path', () => {
    expect(titleFor('/')).toBe('Overview')
  })

  it('returns null for a path the nav does not know', () => {
    // null, not a guessed title -- the top bar then shows nothing rather
    // than labelling a page with someone else's name.
    expect(titleFor('/nope')).toBeNull()
  })
})
