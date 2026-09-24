/**
 * The words the Activity surfaces share: how one log line reads, why a job is
 * waiting, and what a finished hunt came to. They live together because the
 * page, the sheet, the ticker and the job page all say the same things, and
 * three of them saying it slightly differently is how a UI stops being one
 * voice.
 */

import type { Job, JobEvent, JobEventType, ListingChecked } from '@/api/types'
import { LOG_GLYPHS, type LogGlyphLevel, type LogLine } from '@/components/ui/terminal-log'
import { logTime } from '@/lib/time'

/** Some events mean more than their level does: a save is a find (✚), a
 *  rejection is a skip (○). Everything else reads as its level. */
const EVENT_GLYPHS: Partial<Record<JobEventType, LogGlyphLevel>> = {
  listing_discovered: 'new',
  listing_evaluated: 'skip',
  price_found: 'success',
}

/** The glyph a job event's log line carries. */
export function glyphFor(event: JobEvent): LogGlyphLevel {
  return EVENT_GLYPHS[event.event_type] ?? event.level
}

/** One job event as a terminal-log line. */
export function eventLine(event: JobEvent): LogLine {
  return {
    key: `${event.job_id}:${event.seq}`,
    time: logTime(event.ts),
    level: glyphFor(event),
    message: <span className="break-words">{event.message}</span>,
  }
}

/** Why this job is in the queue, in the words the queue shows. */
export function reasonText(job: Job): string {
  switch (job.reason) {
    case 'user':
      return 'you asked'
    case 'created':
      return 'new item'
    case 'slot_freed':
      return 'a slot freed'
    case 'sweep':
      return 'hunting on its own'
    case 'backoff':
      return 'found nothing last time'
    case 'paused':
      return `waiting for ${job.site_name ?? 'the site'} to resume`
    default:
      return job.kind === 'ground' ? 'market price refresh' : 'queued'
  }
}

/** What a finished hunt came to — the History table's Result column. */
export function resultText(job: Job): { text: string; tone: string } {
  if (job.status === 'failed') {
    return { text: job.error ?? 'failed', tone: 'text-rise' }
  }
  const stats = job.stats
  const seen = stats?.listings_checked ?? 0
  if (job.status === 'cancelled') {
    return { text: `cancelled · ${seen} seen`, tone: 'text-ink-3' }
  }
  const found = stats?.new_listings ?? 0
  if (found > 0) {
    return { text: `✚ ${found} new · ${seen} seen`, tone: 'text-lume' }
  }
  return { text: `nothing new · ${seen} seen`, tone: 'text-ink-2' }
}

/** One recheck, as the checks tail says it. The method tag is shown only when
 *  a model was not involved — `llm` is the fallback, not the news. */
export function checkLine(check: ListingChecked, index: number): LogLine {
  const ended = check.status === 'sold' || check.status === 'ended'
  const level: LogGlyphLevel = ended ? 'error' : check.confirmed ? 'success' : 'warn'
  const head = ended ? check.status : check.price ? `$${check.price}` : 'no price'
  const tag = check.method && check.method !== 'llm' ? check.method : null
  return {
    key: `${check.listing_id}:${check.checked_at}:${index}`,
    time: logTime(check.checked_at),
    level,
    message: (
      <span className={check.confirmed ? undefined : 'text-ink-3'}>
        {head} · {check.item_name} · {check.site_name}
        {tag ? <span className="text-ink-3"> · {tag}</span> : null}
        {check.slot_freed ? <span className="text-ink-3"> · slot freed</span> : null}
        {check.confirmed ? null : (
          <span className="text-ink-3"> · unconfirmed — the model is re-reading it</span>
        )}
      </span>
    ),
  }
}

/** Each log level's glyph and color, re-exported so Activity surfaces take words and glyphs from one place. */
export const GLYPHS = LOG_GLYPHS
