import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname, basename, normalize, posix, sep } from 'node:path'
import { builtinModules } from 'node:module'

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
  /from\s+['"].*\/app\//,
  // src/core must never pull in a solver-tier library, even transitively —
  // h3-js is for the solvers' hex-binning, not the core domain.
  /from\s+['"]h3-js['"]/,
]

/**
 * Strip block (`/* ... *\/`, including `/** ... *\/`) and line (`// ...`)
 * comments so the determinism check can't be tripped by a comment merely
 * mentioning `Date.now()` or `Math.random()` (e.g. a doc comment warning
 * against using them). Only the determinism check uses this — the import
 * scan, line-count cap, and header check must keep reading the ORIGINAL
 * source, since the header check looks for text (`PURPOSE:`, `PIVOT:`,
 * `SAFE-TO-DELETE:`) that lives inside comments.
 *
 * BLIND SPOT: this is a regex stripper, not a lexer — it does not
 * understand string or template literals. A `//` or `/* ` inside a string
 * literal would be treated as a comment start, silently excising the rest
 * of that line (or more, for a block-comment-like sequence) from the
 * determinism scan. Accepted rather than fixed: no file in `src/core`
 * currently contains such a literal. Do not make this literal-aware —
 * keep it a stripper, not a lexer.
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

/**
 * Every `import`/`export ... from '...'` specifier in a source file,
 * including bare side-effect imports and dynamic `import(...)` calls.
 * Not a full parser — good enough for the module-specifier strings this
 * codebase actually writes.
 */
function importSpecifiers(src: string): string[] {
  const specs: string[] = []
  const patterns = [/from\s+['"]([^'"]+)['"]/g, /import\(\s*['"]([^'"]+)['"]\s*\)/g]
  for (const rx of patterns) {
    for (const m of src.matchAll(rx)) specs.push(m[1]!)
  }
  return specs
}

/**
 * The single documented exception to "solvers import only from core, h3-js,
 * and node builtins": `metro-feeder` may import `pool-merger`, a sibling
 * solver module a later task creates. Written to match on the SPECIFIER, not
 * the file existing yet, so this test does not have to be revisited when
 * pool-merger.ts lands.
 */
function isMetroFeederPoolMergerException(filePath: string, spec: string): boolean {
  return basename(filePath, '.ts') === 'metro-feeder' && basename(spec) === 'pool-merger'
}

function isAllowedSolverImport(filePath: string, spec: string): boolean {
  if (spec === 'h3-js') return true
  const bare = spec.startsWith('node:') ? spec.slice('node:'.length) : spec
  if (builtinModules.includes(bare)) return true

  if (spec.startsWith('.')) {
    if (isMetroFeederPoolMergerException(filePath, spec)) return true
    // resolve the relative specifier against the importing file's directory
    // and normalize to '/' so "starts with src/core/" is a reliable check
    // regardless of the host path separator.
    const resolved = normalize(join(dirname(filePath), spec)).split(sep).join(posix.sep)
    return resolved === 'src/core' || resolved.startsWith('src/core/')
  }

  return false
}

describe('solvers import boundaries', () => {
  const files = walk('src/solvers')

  it('finds solver source files', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it(
    'src/solvers imports only from src/core, h3-js, and node builtins ' +
      '(plus the documented metro-feeder -> pool-merger exception)',
    () => {
      const offenders: string[] = []
      for (const f of files) {
        const src = readFileSync(f, 'utf8')
        for (const spec of importSpecifiers(src)) {
          if (!isAllowedSolverImport(f, spec)) offenders.push(`${f} :: ${spec}`)
        }
      }
      expect(offenders).toEqual([])
    },
  )

  it('src/solvers is deterministic — no Date.now or bare Math.random', () => {
    const offenders: string[] = []
    for (const f of files) {
      const stripped = stripComments(readFileSync(f, 'utf8'))
      if (/Date\.now\(/.test(stripped)) offenders.push(`${f} :: Date.now`)
      if (/Math\.random\(/.test(stripped)) offenders.push(`${f} :: Math.random`)
    }
    expect(offenders).toEqual([])
  })

  it('no solvers file exceeds 250 lines', () => {
    const tooLong = files
      .map((f) => [f, readFileSync(f, 'utf8').split('\n').length] as const)
      .filter(([, n]) => n > 250)
      .map(([f, n]) => `${f} (${n})`)
    expect(tooLong).toEqual([])
  })

  it('every solvers file carries the 3-line header', () => {
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

  it('a real Date.now() call survives stripping while a commented mention does not', () => {
    const real = 'const t = Date.now()\n'
    const commented = '// Date.now()\n'
    expect(stripComments(real)).toContain('Date.now()')
    expect(stripComments(commented)).not.toContain('Date.now')
    expect(/Date\.now\(/.test(stripComments(real))).toBe(true)
  })
})
