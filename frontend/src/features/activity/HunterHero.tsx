import type { JobsSummary } from '@/api/types'
import { Radar } from '@/components/ui/radar'
import { useInstance } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { countdown, formatToday } from '@/lib/time'
import { ConnectionStatus } from './ConnectionStatus'
import type { Connection } from './liveStream'
import { behindSchedule, checksDue } from './timeline'

/**
 * The hunter's presence as a sentence, then the few numbers that say how the
 * night is going. What needs a person lives in the rail and what happened in
 * the timeline, so nothing here repeats either.
 */
export function HunterHero({
  summary,
  connection,
}: {
  summary?: JobsSummary
  connection: Connection
}) {
  const hunts = summary?.hunts_running ?? 0
  const checks = summary?.checks_running ?? 0
  const busy = hunts + checks > 0
  const nothingYet = summary != null && summary.listings_watched === 0 && summary.last_hunt == null
  const huntEnabled = useInstance().data?.hunt_enabled !== false
  const behind = summary != null && behindSchedule(summary, huntEnabled)

  const eyebrow = `Today · ${formatToday()}`

  return (
    <section className="flex flex-wrap items-end gap-x-8 gap-y-5">
      <div className="flex min-w-0 flex-1 basis-80 items-center gap-4">
        <Radar size={56} glyph animate={busy} />
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-mono text-[12px] tracking-[0.16em] text-ink-3 uppercase">
            {eyebrow}
            <span aria-hidden>·</span>
            <span className="tracking-[0.08em]">
              <ConnectionStatus connection={connection} />
            </span>
          </p>
          <h1
            className={cn(
              'mt-1.5 font-display text-[30px] leading-[1.05] font-semibold tracking-[0.04em] uppercase sm:text-[36px]',
              busy ? 'text-lume' : 'text-ink',
            )}
          >
            {headline(hunts, checks, nothingYet, behind)}
          </h1>
        </div>
      </div>
      {summary && !nothingYet ? (
        <dl className="flex gap-7">
          <Stat
            label="Next check"
            value={
              checksDue(summary) === 'in-line' ? 'in line' : shortCountdown(summary.next_check_at)
            }
          />
          <Stat label="Hunts today" value={String(summary.hunts_today)} />
          <Stat label="Listings tracked" value={String(summary.listings_watched)} />
        </dl>
      ) : null}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col-reverse gap-1 sm:items-end">
      <dt className="font-mono text-[12px] text-ink-3">{label}</dt>
      <dd className="font-mono text-[24px] leading-none font-medium text-ink tnum">{value}</dd>
    </div>
  )
}

function headline(hunts: number, checks: number, nothingYet: boolean, behind: boolean): string {
  if (hunts > 0 && checks > 0) {
    return `Working: ${hunts} ${plural(hunts, 'hunt')}, ${checks} ${plural(checks, 'price check')}`
  }
  if (hunts > 0) return `Working: ${hunts} ${plural(hunts, 'hunt')}`
  if (checks > 0) return `Checking ${checks} ${plural(checks, 'price')}`
  // overdue work with nothing running is news even on a fresh install, where
  // a hunter that was never started is the likeliest reason
  if (behind) return 'Behind schedule'
  if (nothingYet) return 'Nothing has run yet'
  return 'Idle until the next price check'
}

/** The stat reads as a figure, so the countdown drops its "in". */
function shortCountdown(iso: string | null): string {
  return countdown(iso).replace(/^in /, '')
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`
}
