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
      if (/Date\.now\(/.test(src)) offenders.push(`${f} :: Date.now`)
      if (/Math\.random\(/.test(src)) offenders.push(`${f} :: Math.random`)
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
