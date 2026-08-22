import type { ReactNode } from 'react'
import type { RunStatus } from '@/api/types'

/** Active states pulse as dots; terminal states are glyphs — never color alone. */
const STATUS_STYLES: Record<RunStatus, { node: ReactNode; label: string }> = {
  queued: {
    node: <span aria-hidden className="size-2 shrink-0 rounded-full border border-warn" />,
    label: 'Queued',
  },
  running: {
    node: <span aria-hidden className="size-2 shrink-0 animate-pulse rounded-full bg-lume" />,
    label: 'Running',
  },
  succeeded: {
    node: (
      <span aria-hidden className="w-3 shrink-0 text-center font-mono text-xs text-drop">
        ✓
      </span>
    ),
    label: 'Succeeded',
  },
  failed: {
    node: (
      <span aria-hidden className="w-3 shrink-0 text-center font-mono text-xs text-rise">
        ✗
      </span>
    ),
    label: 'Failed',
  },
  cancelled: {
    node: (
      <span aria-hidden className="w-3 shrink-0 text-center font-mono text-xs text-ink-3">
        ◌
      </span>
    ),
    label: 'Cancelled',
  },
}

export function RunStatusDot({ status, withLabel }: { status: RunStatus; withLabel?: boolean }) {
  const { node, label } = STATUS_STYLES[status]
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      {node}
      {withLabel ? <span className="text-xs text-ink-2">{label}</span> : <span className="sr-only">{label}</span>}
    </span>
  )
}
