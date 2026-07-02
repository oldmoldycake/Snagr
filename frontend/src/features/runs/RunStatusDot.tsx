import type { RunStatus } from '@/api/types'
import { cn } from '@/lib/cn'

const STATUS_STYLES: Record<RunStatus, { className: string; label: string }> = {
  queued: { className: 'bg-warn', label: 'Queued' },
  running: { className: 'animate-pulse bg-accent', label: 'Running' },
  succeeded: { className: 'bg-drop', label: 'Succeeded' },
  failed: { className: 'bg-rise', label: 'Failed' },
  cancelled: { className: 'bg-ink-3', label: 'Cancelled' },
}

export function RunStatusDot({ status, withLabel }: { status: RunStatus; withLabel?: boolean }) {
  const { className, label } = STATUS_STYLES[status]
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span aria-hidden className={cn('size-2 shrink-0 rounded-full', className)} />
      {withLabel ? <span className="text-xs text-ink-2">{label}</span> : <span className="sr-only">{label}</span>}
    </span>
  )
}
