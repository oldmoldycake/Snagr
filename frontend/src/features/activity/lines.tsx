/**
 * The words the Activity surfaces share: how one log line reads, why a job is
 * waiting, what a finished hunt came to, what is running and what Hunt now
 * queued. They live together because the page, the sheet, the ticker, the
 * masthead and the job page all say the same things, and three of them saying
 * it slightly differently is how a UI stops being one voice.
 */

import type { Job, JobEvent, JobEventType, ListingChecked } from '@/api/types'
import type { LogGlyphLevel, LogLine } from '@/components/ui/terminal-log'
import { priceMethodLabel } from '@/lib/priceMethod'
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
      return 'room for a new listing'
    case 'sweep':
      return 'hunting on its own'
    case 'backoff':
      return 'found nothing last time'
    case 'paused':
      return waitingForSite(job)
    default:
      return job.kind === 'ground' ? 'market price refresh' : 'queued'
  }
}

/** What a job on a paused site is waiting for, whatever queued it. */
export function waitingForSite(job: Job): string {
  return `waiting for ${job.site_name ?? 'the site'} to resume`
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

/**
 * The raw text behind a failed job's sentence: what its last failed attempt
 * raised, kept on that attempt's error event. It is for whoever runs Snagr,
 * so the job page shows it only on request. Null when there is none.
 */
export function failureDetail(events: JobEvent[]): string | null {
  const detail = events.findLast((event) => event.event_type === 'error' && event.payload?.detail)
    ?.payload?.detail
  return typeof detail === 'string' ? detail : null
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/**
 * What is running, counted by kind: "2 hunts", or "1 hunt, 1 market price, 3
 * price checks". `live` holds market-price refreshes beside hunts, and every
 * place that counts it says it this way, so none of them calls a refresh a
 * hunt. Empty when nothing is running.
 */
export function runningWork(live: Job[], checksRunning = 0): string {
  const hunts = live.filter((job) => job.kind === 'hunt').length
  const marketPrices = live.filter((job) => job.kind === 'ground').length
  return [
    hunts > 0 ? plural(hunts, 'hunt', 'hunts') : null,
    marketPrices > 0 ? plural(marketPrices, 'market price', 'market prices') : null,
    checksRunning > 0 ? plural(checksRunning, 'price check', 'price checks') : null,
  ]
    .filter((part) => part != null)
    .join(', ')
}

/**
 * What one press of Hunt now asked for. A scope fans out into a hunt per
 * (item, site) pair, most of which wait their turn in the queue, so the
 * receipt says how many there are and how they divide; a pair already being
 * hunted is handed back running rather than queued twice.
 */
export function huntReceipt(jobs: Job[]): string {
  if (jobs.length === 0) return 'No sites to search, so nothing was queued'
  const items = new Set(jobs.map((job) => job.item_id)).size
  const sites = new Set(jobs.map((job) => job.site_id)).size
  let hunts: string
  if (jobs.length === 1) hunts = `a hunt for ${jobs[0].label}`
  else if (items === 1) hunts = `${jobs.length} hunts, one per site`
  else if (sites === 1) hunts = `${jobs.length} hunts, one per item`
  else hunts = `${jobs.length} hunts across ${items} items`
  const running = jobs.filter((job) => job.status === 'running').length
  if (running === jobs.length) return `Already running ${hunts}`
  if (running > 0) return `Queued ${hunts} (${running} already running)`
  return `Queued ${hunts}`
}

/**
 * What one press of Check prices asked for. A scope with no tracked listings
 * queues nothing, and "Queued 0" would read as a success that did nothing.
 */
export function checkReceipt(queued: number): string {
  return queued === 0 ? 'Nothing to check' : `Queued ${queued}`
}

/** One recheck, as the checks tail says it. The method tag is shown only when
 *  a model was not involved (see priceMethodLabel). */
export function checkLine(check: ListingChecked, index: number): LogLine {
  const ended = check.status === 'sold' || check.status === 'ended'
  const level: LogGlyphLevel = ended ? 'error' : check.confirmed ? 'success' : 'warn'
  const head = ended ? check.status : check.price ? `$${check.price}` : 'no price'
  const tag = priceMethodLabel(check.method)
  return {
    key: `${check.listing_id}:${check.checked_at}:${index}`,
    time: logTime(check.checked_at),
    level,
    message: (
      <span className={check.confirmed ? undefined : 'text-ink-3'}>
        {head} · {check.item_name} · {check.site_name}
        {tag ? <span className="text-ink-3"> · {tag}</span> : null}
        {check.slot_freed ? <span className="text-ink-3"> · room for a new listing</span> : null}
        {check.confirmed ? null : (
          <span className="text-ink-3"> · unconfirmed · waiting for a second reading</span>
        )}
      </span>
    ),
  }
}
