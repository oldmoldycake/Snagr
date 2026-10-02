/**
 * Photo-check thresholds travel as two-place decimal strings ("0.85") but are
 * edited as whole percentages ("85"), the way the authenticity badge reads a
 * confidence. Two decimal places are exactly the whole percents, so a value
 * survives the round trip unchanged.
 */
export function thresholdToPercent(threshold: string): string {
  return String(Math.round(Number(threshold) * 100))
}

/** The decimal string PATCH /api/me takes for a percentage as typed. */
export function percentToThreshold(percent: string): string {
  return (Number(percent) / 100).toFixed(2)
}
