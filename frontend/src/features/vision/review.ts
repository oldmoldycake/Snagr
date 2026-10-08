import type { ReferenceLabel } from '@/api/types'

/**
 * The queue badge's words for a suggestion: the 0–1 confidence backing it as
 * a percentage, so "real 0.88" reads as "likely real · 88%", the same shape
 * as the listings board's "likely fake" chip.
 */
export function suggestionText(label: ReferenceLabel, confidence: string): string {
  return `likely ${label} · ${Math.round(Number(confidence) * 100)}%`
}
