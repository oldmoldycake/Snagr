import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { throttle } from './throttle'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('throttle', () => {
  it('runs the first call at once', () => {
    const fn = vi.fn()
    throttle(fn, 1_000).run()
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('collapses a burst into one trailing run when the window closes', () => {
    const fn = vi.fn()
    const { run } = throttle(fn, 1_000)
    run()
    run()
    run()
    expect(fn).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(1_000)
    expect(fn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(5_000)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('holds a call that lands right after a trailing run to the next window', () => {
    const fn = vi.fn()
    const { run } = throttle(fn, 1_000)
    run()
    run()
    vi.advanceTimersByTime(1_000)
    run()
    expect(fn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(1_000)
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('runs at once again after a quiet window', () => {
    const fn = vi.fn()
    const { run } = throttle(fn, 1_000)
    run()
    vi.advanceTimersByTime(1_000)
    run()
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('drops a pending run when cancelled', () => {
    const fn = vi.fn()
    const { run, cancel } = throttle(fn, 1_000)
    run()
    run()
    cancel()
    vi.advanceTimersByTime(5_000)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
