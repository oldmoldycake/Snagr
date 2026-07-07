import { useEffect } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { listRuns } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Card, CardBody } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { formatDuration, relativeTime } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'
import { RunButton } from './RunButton'
import { RunStatusDot } from './RunStatusDot'

export function RunsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeRun, setPanelOpen } = useRunEvents()

  const runs = useQuery({
    queryKey: qk.runs(),
    queryFn: () => listRuns(),
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
        <h1 className="font-display text-lg font-semibold text-ink">Runs</h1>
        <RunButton scope="global" label="Run everything" variant="snag" size="sm" />
      </div>

      <Card>
        <CardBody className="px-0 py-1">
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
              action={<RunButton scope="global" label="Run everything" variant="snag" size="sm" />}
            />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Status</TH>
                  <TH>Scope</TH>
                  <TH>Started</TH>
                  <TH className="hidden sm:table-cell">Duration</TH>
                  <TH className="hidden text-right sm:table-cell">Checked</TH>
                  <TH className="hidden text-right sm:table-cell">Prices</TH>
                  <TH className="hidden text-right sm:table-cell">New</TH>
                  <TH className="text-right">Errors</TH>
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
                      <TD>
                        <RunStatusDot status={run.status} withLabel />
                      </TD>
                      <TD className="font-medium text-ink">{run.scope_label}</TD>
                      <TD className="text-xs whitespace-nowrap text-ink-3">{relativeTime(run.created_at)}</TD>
                      <TD className="hidden font-mono text-xs text-ink-2 tnum sm:table-cell">
                        {run.started_at ? formatDuration(run.started_at, run.finished_at) : '—'}
                        {isActive ? <span className="ml-1 text-accent">live</span> : null}
                      </TD>
                      <TD className="hidden text-right font-mono text-ink-2 tnum sm:table-cell">{run.stats?.listings_checked ?? '—'}</TD>
                      <TD className="hidden text-right font-mono text-ink-2 tnum sm:table-cell">{run.stats?.prices_found ?? '—'}</TD>
                      <TD className="hidden text-right font-mono text-ink-2 tnum sm:table-cell">{run.stats?.new_listings ?? '—'}</TD>
                      <TD className="text-right font-mono tnum">
                        {run.stats == null ? (
                          <span className="text-ink-2">—</span>
                        ) : run.stats.errors > 0 ? (
                          <span className="text-rise">{run.stats.errors}</span>
                        ) : (
                          <span className="text-ink-2">0</span>
                        )}
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
