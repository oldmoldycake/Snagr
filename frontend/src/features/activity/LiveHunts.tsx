import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cancelJob } from '@/api/endpoints'
import type { Job } from '@/api/types'
import { Card } from '@/components/ui/card'
import { Radar } from '@/components/ui/radar'
import { useSession } from '@/features/auth/useSession'
import { formatDuration } from '@/lib/time'
import { GLYPHS, glyphFor } from './lines'
import { useJobs } from './JobsProvider'

/** Elapsed re-renders once a second while anything is live. */
function useTick(active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [active])
}

/**
 * Beat two: hunts have a voice. One row per live hunt or grounding pass,
 * showing its latest line — which is the only place on this page a
 * per-hunt fact belongs.
 */
export function LiveHunts({ onOpen }: { onOpen?: () => void }) {
  const { live } = useJobs()
  useTick(live.length > 0)
  if (live.length === 0) return null

  return (
    <section className="space-y-2">
      <h2 className="font-mono text-[10px] tracking-[0.14em] text-ink-3 uppercase">Live hunts</h2>
      <Card className="divide-y divide-hairline">
        {live.map((job) => (
          <LiveHuntRow key={job.id} job={job} onOpen={onOpen} />
        ))}
      </Card>
    </section>
  )
}

function LiveHuntRow({ job, onOpen }: { job: Job; onOpen?: () => void }) {
  const { events } = useJobs()
  const { data: me } = useSession()
  const queryClient = useQueryClient()
  const latest = (events.get(job.id) ?? []).at(-1)
  const glyph = latest ? GLYPHS[glyphFor(latest)] : null

  const cancel = useMutation({
    mutationFn: () => cancelJob(job.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  // the hunter's own work (no watch behind it) is admin-only to cancel
  const canCancel = me != null && (me.role === 'admin' || job.watch_id != null)

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 p-3">
      <Radar size={22} />
      <div className="min-w-0 flex-1 basis-56">
        <p className="truncate text-[13px] font-medium text-ink">
          {job.item_name}
          {job.site_name ? <span className="text-ink-3"> × {job.site_name}</span> : null}
        </p>
        <p className="mt-0.5 truncate font-mono text-[11px] text-ink-2">
          {latest && glyph ? (
            <>
              <span aria-hidden className={glyph.className}>
                {glyph.glyph}
              </span>{' '}
              {latest.message}
            </>
          ) : (
            'Starting up…'
          )}
        </p>
      </div>
      <span className="font-mono text-[11px] text-ink-3 tnum">
        {formatDuration(job.started_at)}
      </span>
      {canCancel ? (
        <button
          type="button"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate()}
          className="font-mono text-[11px] text-rise hover:underline disabled:opacity-50"
        >
          Cancel
        </button>
      ) : null}
      <Link
        to={`/activity/${job.id}`}
        onClick={onOpen}
        className="font-mono text-[11px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume"
      >
        Open →
      </Link>
    </div>
  )
}
