/**
 * Run `fn` at most once per `ms`: the first call runs at once, and any calls
 * inside the window collapse into one more run when it closes, so the last
 * call is never lost. Returns the throttled function and its teardown.
 */
export function throttle(fn: () => void, ms: number): { run: () => void; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending = false

  const close = () => {
    timer = undefined
    if (!pending) return
    pending = false
    fn()
    timer = setTimeout(close, ms)
  }

  return {
    run: () => {
      if (timer !== undefined) {
        pending = true
        return
      }
      fn()
      timer = setTimeout(close, ms)
    },
    cancel: () => {
      clearTimeout(timer)
      timer = undefined
      pending = false
    },
  }
}
