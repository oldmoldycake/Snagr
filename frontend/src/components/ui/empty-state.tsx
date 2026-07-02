import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-hairline px-6 py-12 text-center',
        className,
      )}
    >
      <span aria-hidden className="font-display text-2xl text-ink-3">
        ⌖
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {description ? <p className="max-w-sm text-[13px] text-ink-2">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}
