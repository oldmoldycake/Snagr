import { LABEL_CLEARANCE_PX, labelPx } from './rail'

/**
 * Whether the Ladder's in-range ⌖ label joins "now" in one right-anchored
 * phrase instead of ending at its notch (never left of 42%). Past 55% it would
 * overprint "now"; near the left end, where a target at or above the range
 * high sits, it would overprint the high label. Until the row is measured
 * only the 55% rule applies.
 */
export function ladderTargetJoinsNow(
  targetPos: number,
  targetLabel: string,
  highLabel: string,
  rowPx: number,
): boolean {
  if (targetPos > 55) return true
  if (rowPx <= 0) return false
  const end = (Math.max(targetPos, 42) / 100) * rowPx
  return end - labelPx(targetLabel) < labelPx(highLabel) + LABEL_CLEARANCE_PX
}
