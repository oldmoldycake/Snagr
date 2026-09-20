import type { JobsSummary } from '@/api/types'
import { TerminalLog } from '@/components/ui/terminal-log'
import { checkLine } from './lines'
import { useJobs } from './JobsProvider'

/**
 * Beat two, the other half: checks have a pulse, not a voice. A terminal tail
 * of what this tab has watched happen — held in the browser and never
 * fetched, because 2,400 rows a day is a heartbeat, not history. The one
 * per-listing detail the page shows, and the only place rechecks appear on it.
 */
export function ChecksTail({ summary }: { summary?: JobsSummary }) {
  const { checks } = useJobs()

  return (
    <section className="space-y-2">
      <h2 className="font-mono text-[10px] tracking-[0.14em] text-ink-3 uppercase">
        Checks
        {summary ? (
          <>
            {' · '}
            {summary.checks_running} running · {summary.checks_pending} queued
          </>
        ) : null}
      </h2>
      <div className="rounded-lg border border-hairline bg-well px-4 py-3">
        {checks.length === 0 ? (
          <p className="py-1 font-mono text-[11px] text-ink-3">
            Nothing checked while this page has been open.
          </p>
        ) : (
          <TerminalLog lines={checks.map(checkLine)} />
        )}
      </div>
      <p className="font-mono text-[10.5px] leading-relaxed text-ink-3">
        Checks write no events. This tail is what this tab has seen; it is not fetched, and the
        method is shown only when no model was involved.
      </p>
    </section>
  )
}
