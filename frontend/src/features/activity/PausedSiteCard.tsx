import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateSite } from '@/api/endpoints'
import type { PausedSite } from '@/api/types'
import { Button } from '@/components/ui/button'
import { clockTime, countdown } from '@/lib/time'

/**
 * The circuit breaker, said out loud. A paused site is read by nothing until
 * its pause lifts, which is a thing a person needs told rather than left to
 * infer from a queue that stopped moving.
 */
export function PausedSiteCard({ site }: { site: PausedSite }) {
  const queryClient = useQueryClient()
  const resume = useMutation({
    mutationFn: () => updateSite(site.site_id, { paused_until: null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
  })

  return (
    <div role="alert" className="space-y-2.5 rounded-lg border border-warn/40 bg-warn/[0.07] p-4">
      <div className="flex items-baseline gap-2">
        <span aria-hidden className="text-warn">
          ⚠
        </span>
        <p className="min-w-0 flex-1 text-sm font-semibold text-warn">{site.site_name} paused</p>
        <span className="font-mono text-[11px] text-warn tnum">{countdown(site.paused_until)}</span>
      </div>
      <p className="text-[12.5px] leading-relaxed text-ink-2">
        {site.paused_reason}. Its checks and hunts wait until {clockTime(site.paused_until)}, then
        resume on their own.
      </p>
      <Button variant="warn" size="sm" disabled={resume.isPending} onClick={() => resume.mutate()}>
        Resume now
      </Button>
    </div>
  )
}
