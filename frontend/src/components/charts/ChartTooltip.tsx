import type { ReactNode } from 'react'
import { formatDateTime } from '@/lib/time'

/** Shared tooltip chrome: raised panel, mono values, line-key strokes. */
export function TooltipFrame({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className="rounded-sm border border-hairline bg-overlay px-2.5 py-2 shadow-xl">
      {label ? <p className="mb-1.5 text-[11px] text-ink-3">{label}</p> : null}
      <div className="space-y-1">{children}</div>
    </div>
  )
}

export function TooltipRow({
  color,
  name,
  value,
  note,
}: {
  color: string
  name: string
  value: string
  note?: string
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span aria-hidden className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: color }} />
      <span className="font-mono font-semibold text-ink tnum">{value}</span>
      <span className="text-ink-2">{name}</span>
      {note ? <span className="text-ink-3">{note}</span> : null}
    </div>
  )
}

export function tooltipTimeLabel(ts: number | string | undefined): string {
  if (ts == null) return ''
  return formatDateTime(typeof ts === 'number' ? new Date(ts).toISOString() : ts)
}
