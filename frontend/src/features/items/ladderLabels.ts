import { LABEL_CLEARANCE_PX, labelPx } from './rail'

/**
 * Whether the Ladder's positioned label joins its right-hand neighbour in one
 * right-anchored phrase instead: in range, ⌖ ending at its notch joins "now";
 * while hunting, "now" centred on its marker joins "⌖ target". `pos` is where
 * the label is anchored, in % of the row. Past 55% it would crowd the
 * right-hand label. Once the row is measured it also joins wherever it would
 * overprint a neighbour: the high label (a target at or above the range high
 * sits beside it) or the right-hand label (long prices on a phone-width row).
 * Until then only the 55% rule applies.
 */
export function ladderLabelJoins(
  pos: number,
  align: 'end' | 'center',
  label: string,
  highLabel: string,
  rightLabel: string,
  rowPx: number,
): boolean {
  if (pos > 55) return true
  if (rowPx <= 0) return false
  const width = labelPx(label)
  const end = (pos / 100) * rowPx + (align === 'center' ? width / 2 : 0)
  return (
    end - width < labelPx(highLabel) + LABEL_CLEARANCE_PX ||
    end + LABEL_CLEARANCE_PX > rowPx - labelPx(rightLabel)
  )
}
