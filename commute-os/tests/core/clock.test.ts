import { describe, it, expect, vi } from 'vitest'
import { createClock } from '../../src/core/clock'

const START = 1_757_000_000_000 // fixed epoch ms; no Date.now anywhere
const END = START + 12 * 60 * 60 * 1000

describe('createClock', () => {
  it('starts paused at the start time', () => {
    const c = createClock({ start: START, end: END })
    expect(c.now()).toBe(START)
    expect(c.isPlaying()).toBe(false)
  })

  it('does not advance while paused', () => {
    const c = createClock({ start: START, end: END })
    c.advance(5000)
    expect(c.now()).toBe(START)
  })

  it('advances by realMs * speed while playing', () => {
    const c = createClock({ start: START, end: END, speed: 20 })
    c.play()
    c.advance(1000)
    expect(c.now()).toBe(START + 20_000)
  })

  it('clamps at the end time and auto-pauses', () => {
    const c = createClock({ start: START, end: START + 1000 })
    c.play()
    c.advance(10_000)
    expect(c.now()).toBe(START + 1000)
    expect(c.isPlaying()).toBe(false)
  })

  it('seeks within bounds and clamps outside them', () => {
    const c = createClock({ start: START, end: END })
    c.seek(START + 60_000)
    expect(c.now()).toBe(START + 60_000)
    c.seek(START - 1)
    expect(c.now()).toBe(START)
    c.seek(END + 1)
    expect(c.now()).toBe(END)
  })

  it('notifies subscribers on advance and seek, and stops after unsubscribe', () => {
    const c = createClock({ start: START, end: END, speed: 1 })
    const spy = vi.fn()
    const off = c.subscribe(spy)
    c.seek(START + 1000)
    c.play()
    c.advance(1000)
    expect(spy).toHaveBeenCalledTimes(2)
    expect(spy).toHaveBeenLastCalledWith(START + 2000)
    off()
    c.advance(1000)
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('rejects a non-positive speed', () => {
    const c = createClock({ start: START, end: END })
    expect(() => c.setSpeed(0)).toThrow(/speed/i)
    expect(() => c.setSpeed(-1)).toThrow(/speed/i)
  })
})
