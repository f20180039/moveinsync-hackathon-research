/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// The real stylesheet, read as text. Deliberately not `../App.css?raw`:
// Vite hands that back through its CSS pipeline, not verbatim, and the
// point of this file is to assert what is actually in the source.
// vitest runs with the console/ package root as cwd.
const css = readFileSync(join(process.cwd(), 'src/App.css'), 'utf8')

// jsdom applies no stylesheet, so a rendering test in this repo cannot
// prove the footer sits clear of the page's own content -- it would happily
// pass while the bar covered the last row of every table. What this file
// locks is the source of that class of bug: the declarations that keep the
// fixed bar out of the content's way and keep the expanded panel inside the
// viewport.
function rule(selector: string): string {
  const match = css.match(new RegExp(`\\n${selector.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\s*\\{([^}]*)\\}`))
  if (!match) throw new Error(`no CSS rule found for ${selector}`)
  return match[1]
}

describe('assistant footer layout (CSS contract)', () => {
  it('the bar is pinned to the bottom of the viewport on every page', () => {
    const footer = rule('.assistant-footer')
    expect(footer).toMatch(/position:\s*fixed\s*;/)
    expect(footer).toMatch(/bottom:\s*0\s*;/)
    // Clears the sidebar rather than sitting under it.
    expect(footer).toMatch(/left:\s*var\(--sidebar-width\)\s*;/)
  })

  it('the shell reserves exactly the bar\'s height, from the same token the bar is sized by', () => {
    // Two independently-written numbers is how the last row of a table ends
    // up unreachable underneath a fixed bar. One token, referenced twice.
    expect(css).toMatch(/--assistant-bar-height:\s*\d+px\s*;/)
    expect(rule('.shell__content')).toMatch(/padding:[^;]*calc\(var\(--assistant-bar-height\)/)
    expect(rule('.assistant-footer__panel')).toMatch(/var\(--assistant-bar-height\)/)
  })

  it('the expanded conversation is capped and scrolls itself, so the composer always stays', () => {
    const panel = rule('.assistant-footer__panel')
    expect(panel).toMatch(/max-height:\s*min\(/)
    expect(panel).toMatch(/overflow-y:\s*auto\s*;/)
  })

  it('both states share one centred measure, so expanding does not move the composer', () => {
    expect(rule('.assistant-footer__column')).toMatch(/width:\s*min\(760px,\s*100%\)\s*;/)
    expect(rule('.assistant-footer__column')).toMatch(/margin:\s*0 auto\s*;/)
  })

  it('narrow viewports give the footer the full width, where the sidebar is not a left column', () => {
    expect(css).toMatch(/@media \(max-width: 900px\) \{\s*\.assistant-footer \{\s*left:\s*0\s*;/)
  })
})
