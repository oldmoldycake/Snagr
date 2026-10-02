import type { ItemDetail } from '@/api/types'
import { countdown, relativeTime } from '@/lib/time'

/** What the last hunt came to. ItemDetail carries the outcome, not the
 *  count — the count is on the job, one click away in the History table. */
const LAST_RESULT = {
  found: 'found a listing',
  nothing: 'nothing new',
  failed: 'failed',
  cancelled: 'cancelled',
} as const

/**
 * How many listings an item tracks against its limit, in the words the
 * Tracking card uses. Lowering the limit, or tracking a listing again by
 * hand, can leave a watch over it, and the count says so rather than
 * clamping: the page lists every one of them.
 */
export function trackingCount(tracked: number, max: number): string {
  const count = `tracking ${tracked} of ${max} ${max === 1 ? 'listing' : 'listings'}`
  return tracked > max ? `${count} · ${tracked - max} over the limit` : count
}

/**
 * The item page's hunting line while no hunt is running: how full the watch
 * is, whether Snagr is looking for more, and what the last hunt came to.
 * `tracked` is the page's own count of active listings, so a listing just
 * switched off reads the same here as in the Tracking card.
 */
export function trackingLine(detail: ItemDetail, tracked: number, huntingOff: boolean): string {
  const { hunt } = detail
  const count = trackingCount(tracked, detail.max_listings)
  if (huntingOff) return `${count} · hunting is off on this server`
  const open = detail.max_listings - tracked
  const parts = [count]
  if (open <= 0) {
    // a full watch is never hunted on its own; a person's hunt is a swap
    parts.push('Hunt for better swaps out the weakest')
  } else if (!hunt.enabled) {
    // a switched-off watch has nothing queued on its own, so there is no "next"
    parts.push('hunting off — only when you press Hunt now')
  } else {
    parts.push(`looking for ${open} more`)
    if (hunt.next_at != null) {
      parts.push(
        `next hunt ${countdown(hunt.next_at)}${hunt.backoff_minutes != null ? ' (slowed down after finding nothing)' : ''}`,
      )
    }
  }
  if (hunt.last_at != null && hunt.last_result != null) {
    // a full watch was never going to save anything, so "nothing new" would be
    // describing the rule rather than the hunt
    const outcome =
      open <= 0 && hunt.last_result === 'nothing' ? 'nothing better' : LAST_RESULT[hunt.last_result]
    parts.push(`last hunt ${relativeTime(hunt.last_at)}, ${outcome}`)
  }
  return parts.join(' · ')
}
