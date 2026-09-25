import { useState } from 'react'
import type { JobsSummary } from '@/api/types'
import { TerminalLog } from '@/components/ui/terminal-log'
import { checkLine } from './lines'
import { useJobs } from './JobsProvider'

/**
 * Checks have a pulse, not a voice: one line under "now", with the terminal
 * tail of what this tab has watched happen folded behind it. The tail is held
 * in the browser and never fetched, because 2,400 rows a day is a heartbeat,
 * not history — and its method tag shows only when no model was involved.
 */
export function ChecksTail({ summary }: { summary?: JobsSummary }) {
  const { checks } = useJobs()
  const [open, setOpen] = useState(false)
  const running = summary?.checks_running ?? 0
  if (running === 0 && checks.length === 0) return null

  return (
    <div className="space-y-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-2 gap-y-1 text-left font-mono text-[11px] text-ink-3 hover:text-ink-2"
      >
        {running > 0 ? (
          <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-lume" />
        ) : null}
        <span className="text-ink-2">
          {running > 0
            ? `${running} price ${running === 1 ? 'check' : 'checks'} running`
            : 'Price checks'}
        </span>
        <span>· {checks.length} seen while this page has been open</span>
        <span className="ml-auto tracking-[0.08em] uppercase">{open ? 'Hide ▴' : 'Show ▾'}</span>
      </button>
      {open ? (
        <div className="rounded-lg border border-hairline bg-well px-4 py-3">
          {checks.length === 0 ? (
            <p className="py-1 font-mono text-[11px] text-ink-3">
              Nothing checked while this page has been open.
            </p>
          ) : (
            <TerminalLog lines={checks.map(checkLine)} />
          )}
        </div>
      ) : null}
    </div>
  )
}
