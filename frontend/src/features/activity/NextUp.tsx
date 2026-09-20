import { useQuery } from '@tanstack/react-query'
import { listJobs } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Job, JobsSummary } from '@/api/types'
import { Card } from '@/components/ui/card'
import { countdown } from '@/lib/time'
import { reasonText } from './lines'

const PENDING = { status: 'pending', kind: 'hunt,ground', per_page: 8 } as const

/**
 * Beat three, part one: what the hunter will do next. Hunts and grounding get
 * a row each because each is a decision somebody might disagree with; checks
 * get one line, because forty-four of them are a cadence, not a list.
 */
export function NextUp({ summary }: { summary?: JobsSummary }) {
  const queued = useQuery({
    queryKey: qk.jobs(PENDING),
    queryFn: () => listJobs(PENDING),
  })

  const rows = queued.data?.data ?? []
  const checks = summary?.checks_pending ?? 0
  if (rows.length === 0 && checks === 0) return null

  return (
    <section className="space-y-2">
      <h2 className="font-mono text-[10px] tracking-[0.14em] text-ink-3 uppercase">Next up</h2>
      <Card className="divide-y divide-hairline">
        {rows.map((job) => (
          <QueuedRow key={job.id} job={job} />
        ))}
        {checks > 0 ? (
          <div className="flex flex-wrap items-baseline gap-x-2 p-3 font-mono text-[11px]">
            <span aria-hidden className="w-3 text-center text-ink-3">
              ◌
            </span>
            <span className="font-semibold text-ink">{checks} checks</span>
            <span className="min-w-0 flex-1 text-ink-3">spread over the coming half hour</span>
            <span className="text-ink-2 tnum">{countdown(summary?.next_check_at)}</span>
          </div>
        ) : null}
      </Card>
    </section>
  )
}

function QueuedRow({ job }: { job: Job }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 p-3 font-mono text-[11px]">
      <span aria-hidden className="w-3 text-center text-ink-3">
        ◌
      </span>
      <span className="font-semibold text-ink">
        {job.item_name}
        {job.site_name ? <span className="font-normal text-ink-3"> × {job.site_name}</span> : null}
      </span>
      <span className="min-w-0 flex-1 text-ink-3">
        {job.kind === 'ground' ? 'market price' : 'hunt'} · {reasonText(job)}
      </span>
      <span className="text-ink-2 tnum">{countdown(job.run_after)}</span>
    </div>
  )
}
