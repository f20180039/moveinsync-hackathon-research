import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom applies no stylesheet, so a rendering test in this repo CANNOT
// prove the assistant panel fits a short viewport -- it would happily pass
// while the composer is clipped away, which is exactly how the reported bug
// survived. The pixel verification is done separately in headless Chrome
// (see the task report: real viewport boxes measured at 1280x768, 1280x600,
// 390x600 and 1280x460, before and after).
//
// What this file locks is the source of the bug: three CSS declarations
// that, if any one of them regresses, put the panel back into the state
// where its own content overflows its max-height box and `overflow: hidden`
// clips the bottom of it. Each assertion names the value that was wrong.
// vitest runs with the console/ package root as cwd.
const css = readFileSync(join(process.cwd(), 'src/App.css'), 'utf8')

function rule(selector: string): string {
  // Matches `\n<selector> {  ... }` -- the declarations of exactly one rule.
  const match = css.match(new RegExp(`\\n${selector.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\s*\\{([^}]*)\\}`))
  if (!match) throw new Error(`no CSS rule found for ${selector}`)
  return match[1]
}

describe('floating assistant panel layout (CSS contract)', () => {
  it('the message list can shrink to nothing and scrolls internally', () => {
    const history = rule('.assistant-panel__history')

    // The bug: a flex item's default min-height is its content size, so
    // `min-height: 80px` made the list refuse to shrink, pushed the panel's
    // content past its max-height and clipped the composer.
    expect(history).toMatch(/min-height:\s*0\s*;/)
    expect(history).not.toMatch(/min-height:\s*(?!0\s*;)\S+/)
    expect(history).toMatch(/overflow-y:\s*auto\s*;/)
  })

  it('the suggestion chips give way instead of eating the panel', () => {
    const chips = rule('.assistant-panel__chips')

    // Four wrapped chips measured 177px -- a third of the panel that no
    // viewport height could reclaim while this was `flex-shrink: 0`.
    expect(chips).not.toMatch(/flex-shrink:\s*0\s*;/)
    expect(chips).toMatch(/flex:\s*0 1 auto\s*;/)
    expect(chips).toMatch(/min-height:\s*0\s*;/)
    expect(chips).toMatch(/overflow-y:\s*auto\s*;/)
    expect(chips).toMatch(/max-height:/)
  })

  it("the panel's height budget is the space above the launcher, not a flat 70vh", () => {
    const panel = rule('.assistant-panel')

    // 70vh left ~30vh unusable above the panel while its children fought
    // over a box too small for all of them.
    expect(panel).not.toMatch(/max-height:\s*min\(70vh/)
    expect(panel).toMatch(/max-height:\s*min\(640px,\s*calc\(100vh -/)
    // The subtraction has to account for the launcher itself (56px) or the
    // panel overlaps it at short heights.
    expect(panel).toMatch(/calc\(100vh - 56px/)
  })

  it('the composer never shrinks, so it is always the part that stays', () => {
    expect(rule('.assistant-panel__form')).toMatch(/flex-shrink:\s*0\s*;/)
    expect(rule('.assistant-panel__header')).toMatch(/flex-shrink:\s*0\s*;/)
  })
})
