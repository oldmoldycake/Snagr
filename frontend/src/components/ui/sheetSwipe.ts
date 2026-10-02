/** Share of the sheet's height a slow drag must cover before letting go closes it. */
const CLOSE_SHARE = 0.25
/** Average downward speed from press to let-go, in px per ms, that makes a short drag a flick. */
const FLICK_SPEED = 0.4
/** Least travel that counts as a flick, so a tap that wobbles on the handle never closes the sheet. */
const FLICK_MIN = 20

/**
 * Whether letting go of a bottom sheet's grab handle closes the sheet: once
 * it has been pulled down a quarter of its height, or flicked down. `distance`
 * is how far below the press the finger let go (px), `ms` how long it was
 * held, `height` the sheet's own height.
 */
export function swipeCloses(distance: number, ms: number, height: number): boolean {
  if (distance <= 0) return false
  return distance >= height * CLOSE_SHARE || (distance >= FLICK_MIN && distance / ms >= FLICK_SPEED)
}
