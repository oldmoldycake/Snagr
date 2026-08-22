import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { listRuns } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { Radar } from '@/components/ui/radar'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { LOG_GLYPHS } from '@/components/ui/terminal-log'
import { formatDuration, relativeTime } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'
import { RunButton } from './RunButton'
import { RunStatusDot } from './RunStatusDot'

/** The live sweep, compact: radar + state + latest event; the log lives on the run page. */
function LiveSweepHero() {
  const { activeRun, events, setPanelOpen } = useRunEvents()
  const [, setTick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])

  if (!isRunActive(activeRun) || !activeRun) return null
  const latest = events[events.length - 1]
  const level = latest ? LOG_GLYPHS[latest.level] : null

  return (
    <div className="rounded-lg border border-lume/25 bg-surface p-4">
      <div className="flex items-center gap-4">
        <Radar size={44} glyph />
        <div className="min-w-0 flex-1">
          <p className="font-display text-[22px] leading-tight font-semibold tracking-[0.04em] text-lume uppercase">
            Sweeping — {activeRun.scope_label}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-ink-3 tnum">
            {activeRun.started_at
              ? `${formatDuration(activeRun.started_at)} elapsed`
              : 'queued — waiting for the agent'}
            {latest && level ? (
              <>
                {' · '}
                <span aria-hidden className={level.className}>
                  {level.glyph}
                </span>{' '}
                <span className="text-ink-2">{latest.message}</span>
              </>
            ) : null}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPanelOpen(true)}
          className="shrink-0 font-mono text-[11px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume"
        >
          Watch ↗
        </button>
        <Link
          to={`/runs/${activeRun.id}`}
          className="shrink-0 font-mono text-[11px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume"
        >
          Open →
        </Link>
      </div>
    </div>
  )
}

export function RunsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeRun, setPanelOpen } = useRunEvents()
  const [page, setPage] = useState(1)

  const runs = useQuery({
    queryKey: qk.runs({ page }),
    queryFn: () => listRuns({ page }),
    placeholderData: keepPreviousData,
  })

  // keep the running row's status fresh while a run is active
  const active = isRunActive(activeRun)
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => void queryClient.invalidateQueries({ queryKey: ['runs'] }), 5000)
    return () => clearInterval(t)
  }, [active, queryClient])

  const rows = runs.data?.data ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">
          Runs
        </h1>
        <RunButton scope="global" label="Run everything" variant="primary" size="sm" />
      </div>

      <LiveSweepHero />

      <div className="flex items-baseline gap-3">
        <h2 className="font-display text-[17px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
          Previous sweeps
        </h2>
        {runs.data ? (
          <span className="font-mono text-[11px] text-ink-3 tnum">{runs.data.meta.total} runs</span>
        ) : null}
      </div>

      <Card>
        {runs.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            className="m-4 border-0"
            title="No runs yet"
            description="Start a run to have the agent check prices and discover listings — you can watch it work live."
            action={<RunButton scope="global" label="Run everything" variant="primary" size="sm" />}
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH className="w-8" />
                  <TH>When</TH>
                  <TH>Scope</TH>
                  <TH className="hidden sm:table-cell">Results</TH>
                  <TH className="hidden text-right sm:table-cell">Duration</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((run) => {
                  const isActive = run.status === 'queued' || run.status === 'running'
                  return (
                    <TR
                      key={run.id}
                      data-clickable="true"
                      onClick={() => (isActive ? setPanelOpen(true) : navigate(`/runs/${run.id}`))}
                    >
                      <TD className="pr-0">
                        <RunStatusDot status={run.status} />
                      </TD>
                      <TD className="font-mono text-xs whitespace-nowrap text-ink-3">
                        {relativeTime(run.created_at)}
                      </TD>
                      <TD className="font-medium text-ink">
                        {run.scope_label}
                        <span className="ml-2 font-mono text-[10.5px] font-normal text-ink-3">
                          {run.user_id === null ? 'system' : ''}
                        </span>
                      </TD>
                      <TD className="hidden font-mono text-xs text-ink-2 tnum sm:table-cell">
                        {run.status === 'failed' ? (
                          <span className="text-rise">{run.error ?? 'failed'}</span>
                        ) : run.status === 'cancelled' ? (
                          <span className="text-ink-3">
                            cancelled{run.stats ? ` — ${run.stats.listings_checked} checked` : ''}
                          </span>
                        ) : run.stats ? (
                          <>
                            {run.stats.listings_checked} checked · {run.stats.prices_found} prices
                            {run.stats.new_listings > 0 ? ` · ${run.stats.new_listings} new` : ''}
                            {run.stats.errors > 0 ? (
                              <span className="text-rise">
                                {' '}
                                · {run.stats.errors} {run.stats.errors === 1 ? 'error' : 'errors'}
                              </span>
                            ) : null}
                          </>
                        ) : isActive ? (
                          <span className="text-lume">live</span>
                        ) : (
                          '—'
                        )}
                      </TD>
                      <TD className="hidden text-right font-mono text-xs text-ink-2 tnum sm:table-cell">
                        {run.started_at ? formatDuration(run.started_at, run.finished_at) : '—'}
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
            {runs.data && runs.data.meta.total > runs.data.meta.per_page ? (
              <div className="flex justify-end border-t border-hairline bg-well px-4 py-2">
                <Pagination meta={runs.data.meta} onPage={setPage} />
              </div>
            ) : null}
          </>
        )}
      </Card>
    </div>
  )
}
