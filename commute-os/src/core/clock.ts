/**
 * PURPOSE: a deterministic simulation clock driving cab animation and playback.
 * PIVOT: if the statement needs a longer horizon, widen start/end at the call
 *        site; nothing here assumes a day.
 * SAFE-TO-DELETE: no — every before/after playback depends on it.
 */

export type SimClock = {
  now(): number
  seek(ms: number): void
  /** advance by wall-clock ms; scaled by speed. Caller owns the timer. */
  advance(realMs: number): void
  play(): void
  pause(): void
  setSpeed(n: number): void
  isPlaying(): boolean
  subscribe(fn: (ms: number) => void): () => void
}

/**
 * No setInterval and no Date.now inside core: the UI calls advance() from
 * requestAnimationFrame, and tests call it directly. That is what makes golden
 * tests byte-stable.
 */
export function createClock(opts: { start: number; end: number; speed?: number }): SimClock {
  const { start, end } = opts
  let speed = opts.speed ?? 1
  let current = start
  let playing = false
  const subs = new Set<(ms: number) => void>()

  const emit = (): void => { for (const fn of subs) fn(current) }
  const clamp = (ms: number): number => Math.min(end, Math.max(start, ms))

  return {
    now: () => current,
    isPlaying: () => playing,
    play: () => { playing = true },
    pause: () => { playing = false },
    setSpeed: (n: number) => {
      if (!(n > 0)) throw new Error(`clock speed must be > 0, got ${n}`)
      speed = n
    },
    seek: (ms: number) => { current = clamp(ms); emit() },
    advance: (realMs: number) => {
      if (!playing) return
      current = clamp(current + realMs * speed)
      if (current >= end) playing = false
      emit()
    },
    subscribe: (fn) => { subs.add(fn); return () => { subs.delete(fn) } },
  }
}
