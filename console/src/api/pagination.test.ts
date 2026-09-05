import { describe, expect, it } from 'vitest'
import { paginate } from './pagination.ts'

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i + 1)
}

describe('paginate', () => {
  it('splits into pages of the requested size', () => {
    const result = paginate(range(60), 1, 25)
    expect(result.items).toEqual(range(25))
    expect(result.totalPages).toBe(3)
    expect(result.total).toBe(60)
    expect(result.from).toBe(1)
    expect(result.to).toBe(25)
  })

  it('computes "Showing 26–50 of 208"-style numbers for page 2', () => {
    const result = paginate(range(208), 2, 25)
    expect(result.from).toBe(26)
    expect(result.to).toBe(50)
    expect(result.total).toBe(208)
    expect(result.totalPages).toBe(9)
  })

  it('the last page can be a partial page', () => {
    const result = paginate(range(208), 9, 25)
    expect(result.items).toHaveLength(8)
    expect(result.from).toBe(201)
    expect(result.to).toBe(208)
  })

  it('clamps a page number above the last page to the last page', () => {
    const result = paginate(range(60), 999, 25)
    expect(result.page).toBe(3)
    expect(result.from).toBe(51)
    expect(result.to).toBe(60)
  })

  it('clamps a page number below 1 to page 1', () => {
    const result = paginate(range(60), 0, 25)
    expect(result.page).toBe(1)
    expect(result.from).toBe(1)
  })

  it('handles an empty list', () => {
    const result = paginate([], 1, 25)
    expect(result.items).toEqual([])
    expect(result.total).toBe(0)
    expect(result.totalPages).toBe(1)
    expect(result.from).toBe(0)
    expect(result.to).toBe(0)
  })

  it('handles fewer items than one page', () => {
    const result = paginate(range(8), 1, 25)
    expect(result.items).toHaveLength(8)
    expect(result.totalPages).toBe(1)
    expect(result.from).toBe(1)
    expect(result.to).toBe(8)
  })
})
