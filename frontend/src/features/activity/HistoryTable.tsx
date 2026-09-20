import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { listJobs } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Job } from '@/api/types'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { cn } from '@/lib/cn'
import { clockTime, formatMillis, formatTokens } from '@/lib/time'
import { JobStatusDot } from './JobStatusDot'
import { resultText } from './lines'

type Filter = 'hunt' | 'recheck' | 'ground' | 'all'

const FILTERS: readonly { value: Filter; label: string }[] = [
  { value: 'hunt', label: 'Hunts' },
  { value: 'recheck', label: 'Checks' },
  { value: 'ground', label: 'Grounding' },
  { value: 'all', label: 'All' },
]

const REMEMBERED = 'snagr:activity-filter'
const FINISHED = 'done,failed,cancelled'

/**
 * Beat three, part two: the ledger. Hunts are the default because they are
 * the decisions; Checks exists to debug one site and is never where you land,
 * because 2,400 rows a day would bury everything else.
 */
export function HistoryTable() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('hunt')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const held = localStorage.getItem(REMEMBERED)
    if (held && FILTERS.some((f) => f.value === held)) setFilter(held as Filter)
  }, [])

  const params = {
    status: FINISHED,
    page,
    ...(filter === 'all' ? {} : { kind: filter }),
  }
  const history = useQuery({
    queryKey: qk.jobs(params),
    queryFn: () => listJobs(params),
    placeholderData: keepPreviousData,
  })

  const rows = history.data?.data ?? []

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="font-display text-[17px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
          History
        </h2>
        {history.data ? (
          <span className="font-mono text-[11px] text-ink-3 tnum">
            {history.data.meta.total} {filter === 'hunt' ? 'hunts' : 'jobs'}
          </span>
        ) : null}
        <Segmented
          className="ml-auto"
          ariaLabel="What to show"
          options={FILTERS}
          value={filter}
          onChange={(value) => {
            setFilter(value)
            setPage(1)
            localStorage.setItem(REMEMBERED, value)
          }}
        />
      </div>

      <Card>
        {history.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            className="m-4 border-0"
            title="Nothing has happened yet"
            description="Add an item and the hunter starts looking. Prices are re-checked on their own from then on."
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH className="w-8" />
                  <TH>When</TH>
                  <TH>{filter === 'recheck' ? 'Check' : 'Hunt'}</TH>
                  <TH className="hidden sm:table-cell">Result</TH>
                  <TH className="hidden text-right sm:table-cell">Took</TH>
                  <TH className="hidden text-right sm:table-cell">Tokens</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((job) => (
                  <HistoryRow
                    key={job.id}
                    job={job}
                    onOpen={
                      job.kind === 'recheck' ? undefined : () => navigate(`/activity/${job.id}`)
                    }
                  />
                ))}
              </TBody>
            </Table>
            {history.data && history.data.meta.total > history.data.meta.per_page ? (
              <div className="flex justify-end border-t border-hairline bg-well px-4 py-2">
                <Pagination meta={history.data.meta} onPage={setPage} />
              </div>
            ) : null}
          </>
        )}
      </Card>
      <p className="font-mono text-[10.5px] leading-relaxed text-ink-3">
        Checks are for debugging a site, never the default — they are a heartbeat, and the prices
        they found live on the item pages. “system” marks work the hunter queued for itself.
      </p>
    </section>
  )
}

function HistoryRow({ job, onOpen }: { job: Job; onOpen?: () => void }) {
  const [open, setOpen] = useState(false)
  const result = resultText(job)
  const expandable = onOpen == null

  return (
    <>
      <TR
        data-clickable="true"
        onClick={onOpen ?? (() => setOpen((v) => !v))}
      >
        <TD className="pr-0">
          <JobStatusDot status={job.status} />
        </TD>
        <TD className="font-mono text-xs whitespace-nowrap text-ink-3 tnum">
          {clockTime(job.finished_at ?? job.created_at)}
        </TD>
        <TD className="font-medium text-ink">
          {job.item_name}
          {job.site_name ? <span className="text-ink-3"> × {job.site_name}</span> : null}
          {job.user_id === null ? (
            <span className="ml-2 font-mono text-[10.5px] font-normal text-ink-3">system</span>
          ) : null}
        </TD>
        <TD className={cn('hidden font-mono text-xs sm:table-cell tnum', result.tone)}>
          {result.text}
        </TD>
        <TD className="hidden text-right font-mono text-xs text-ink-2 sm:table-cell tnum">
          {formatMillis(job.stats?.duration_ms)}
        </TD>
        <TD className="hidden text-right font-mono text-xs text-ink-2 sm:table-cell tnum">
          {formatTokens((job.stats?.tokens_in ?? 0) + (job.stats?.tokens_out ?? 0))}
        </TD>
      </TR>
      {expandable && open ? (
        <TR>
          <TD />
          <TD colSpan={5} className="font-mono text-[11px] text-ink-3">
            {[
              job.stats?.method,
              job.stats?.transport,
              formatMillis(job.stats?.duration_ms),
              job.error,
            ]
              .filter(Boolean)
              .join(' · ')}
          </TD>
        </TR>
      ) : null}
    </>
  )
}
