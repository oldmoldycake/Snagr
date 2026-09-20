import type { JobsSummary } from '@/api/types'
import { Radar } from '@/components/ui/radar'
import { cn } from '@/lib/cn'
import { countdown, relativeTime } from '@/lib/time'
import { resultText } from './lines'

/**
 * Beat one: the hunter's presence as a sentence. Sweeping or quiet, and what
 * happens next — never what happened, which is the ledger's job.
 */
export function HunterHero({ summary }: { summary?: JobsSummary }) {
  const hunts = summary?.hunts_running ?? 0
  const checks = summary?.checks_running ?? 0
  const busy = hunts + checks > 0
  const nothingYet = summary != null && summary.listings_watched === 0 && summary.last_hunt == null

  return (
    <div
      className={cn(
        'rounded-lg border bg-surface p-4',
        busy ? 'border-lume/25' : 'border-hairline',
      )}
    >
      <div className="flex items-center gap-4">
        <Radar size={44} glyph animate={busy} />
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              'font-display text-[22px] leading-tight font-semibold tracking-[0.04em] uppercase',
              busy ? 'text-lume' : 'text-ink',
            )}
          >
            {headline(hunts, checks, nothingYet, summary)}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-ink-3 tnum">
            {subline(summary, nothingYet)}
          </p>
        </div>
      </div>
    </div>
  )
}

function headline(
  hunts: number,
  checks: number,
  nothingYet: boolean,
  summary?: JobsSummary,
): string {
  if (hunts > 0 && checks > 0) {
    return `Sweeping — ${hunts} ${plural(hunts, 'hunt')} · ${checks} ${plural(checks, 'check')}`
  }
  if (hunts > 0) return `Sweeping — ${hunts} ${plural(hunts, 'hunt')}`
  if (checks > 0) return `Checking — ${checks} live`
  if (nothingYet) return 'Quiet — nothing yet'
  return `Quiet — next check ${countdown(summary?.next_check_at)}`
}

function subline(summary: JobsSummary | undefined, nothingYet: boolean): string {
  if (summary == null) return ''
  if (nothingYet) return 'Add an item and the hunter starts looking for it.'

  const parts: string[] = []
  const paused = summary.paused_sites[0]
  if (paused) parts.push(`⚠ ${paused.site_name} paused until ${clock(paused.paused_until)}`)
  parts.push(`${summary.listings_watched} listings watched`)
  if (summary.hunts_running + summary.checks_running > 0 && summary.next_check_at) {
    parts.push(`next check ${countdown(summary.next_check_at)}`)
  }
  parts.push(`${summary.hunts_today} hunts today`)
  if (summary.last_hunt?.finished_at) {
    parts.push(
      `last hunt ${relativeTime(summary.last_hunt.finished_at)}: ${resultShort(summary.last_hunt)}`,
    )
  }
  return parts.join(' · ')
}

function resultShort(job: JobsSummary['last_hunt']): string {
  return job ? resultText(job).text.replace(/^✚ /, '') : ''
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`
}
