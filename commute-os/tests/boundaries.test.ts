import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.ts')) out.push(p)
  }
  return out
}

const FORBIDDEN = [
  /from\s+['"]react['"]/,
  /from\s+['"]next[/'"]/,
  /from\s+['"].*\/solvers\//,
  /from\s+['"].*\/ui\//,
  /from\s+['"].*\/ai\//,
]

/**
 * Strip block (`/* ... *\/`, including `/** ... *\/`) and line (`// ...`)
 * comments so the determinism check can't be tripped by a comment merely
 * mentioning `Date.now()` or `Math.random()` (e.g. a doc comment warning
 * against using them). Only the determinism check uses this — the import
 * scan, line-count cap, and header check must keep reading the ORIGINAL
 * source, since the header check looks for text (`PURPOSE:`, `PIVOT:`,
 * `SAFE-TO-DELETE:`) that lives inside comments.
 */
export function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
}

describe('core import boundaries', () => {
  const files = walk('src/core')

  it('finds core source files', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it('src/core never imports react, next, solvers, ui or ai', () => {
    const offenders: string[] = []
    for (const f of files) {
      const src = readFileSync(f, 'utf8')
      for (const rx of FORBIDDEN) if (rx.test(src)) offenders.push(`${f} :: ${rx}`)
    }
    expect(offenders).toEqual([])
  })

  it('src/core is deterministic — no Date.now or bare Math.random', () => {
    const offenders: string[] = []
    for (const f of files) {
      const src = readFileSync(f, 'utf8')
      const stripped = stripComments(src)
      if (/Date\.now\(/.test(stripped)) offenders.push(`${f} :: Date.now`)
      if (/Math\.random\(/.test(stripped)) offenders.push(`${f} :: Math.random`)
    }
    expect(offenders).toEqual([])
  })

  it('no core file exceeds 250 lines', () => {
    const tooLong = files
      .map((f) => [f, readFileSync(f, 'utf8').split('\n').length] as const)
      .filter(([, n]) => n > 250)
      .map(([f, n]) => `${f} (${n})`)
    expect(tooLong).toEqual([])
  })

  it('every core file carries the 3-line header', () => {
    const missing = files.filter((f) => {
      const src = readFileSync(f, 'utf8')
      return !(src.includes('PURPOSE:') && src.includes('PIVOT:') && src.includes('SAFE-TO-DELETE:'))
    })
    expect(missing).toEqual([])
  })
})

describe('stripComments', () => {
  it('does not flag Date.now() or Math.random() merely mentioned in a comment', () => {
    const src = '// NEVER Date.now() or Math.random() here\nconst x = 1\n'
    const stripped = stripComments(src)
    expect(/Date\.now\(/.test(stripped)).toBe(false)
    expect(/Math\.random\(/.test(stripped)).toBe(false)
  })

  it('still flags a real Date.now() call outside any comment', () => {
    const src = 'const t = Date.now()\n'
    const stripped = stripComments(src)
    expect(/Date\.now\(/.test(stripped)).toBe(true)
  })
})
