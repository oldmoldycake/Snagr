import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateSite } from '@/api/endpoints'
import type { PausedSite } from '@/api/types'

/**
 * The circuit breaker, said out loud. A paused site is read by nothing until
 * its pause lifts, which is a thing a person needs told rather than left to
 * infer from a queue that stopped moving.
 */
export function PausedSiteBanner({ site }: { site: PausedSite }) {
  const queryClient = useQueryClient()
  const resume = useMutation({
    mutationFn: () => updateSite(site.site_id, { paused_until: null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
  })

  const until = new Date(site.paused_until).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-sm border border-warn/40 bg-warn/10 px-3 py-2.5 text-[13px] text-ink-2"
    >
      <span aria-hidden className="text-warn">
        ⚠
      </span>
      <p className="min-w-0 flex-1">
        <span className="font-semibold text-ink">
          {site.site_name} paused until {until}
        </span>{' '}
        — {site.paused_reason}. Its checks and hunts wait; nothing is retried until then.
      </p>
      <button
        type="button"
        disabled={resume.isPending}
        onClick={() => resume.mutate()}
        className="shrink-0 font-mono text-[11px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume disabled:opacity-50"
      >
        Resume now →
      </button>
    </div>
  )
}
