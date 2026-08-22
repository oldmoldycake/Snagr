import { cn } from '@/lib/cn'
import { formatMoney, fromCents, toCents } from '@/lib/money'

/**
 * Distance-to-target meter: fill = target/best, so a full bar means the price
 * has descended to the target. Lume within 5% — "in striking distance". The
 * gap label carries the number; color is never the only channel.
 */
export function MeterToTarget({
  best,
  target,
  currency = 'USD',
  className,
}: {
  best: string | null
  target: string | null
  currency?: string
  className?: string
}) {
  const b = toCents(best)
  const t = toCents(target)
  if (b == null || t == null || b <= 0 || t <= 0) {
    return <span className={cn('font-mono text-xs text-ink-3', className)}>—</span>
  }

  const gap = b - t
  const fill = Math.max(0, Math.min(1, t / b))
  const close = fill >= 0.95

  return (
    <span className={cn('flex items-center justify-end gap-2', className)}>
      <span aria-hidden className="h-1 w-14 shrink-0 overflow-hidden rounded-full bg-raised">
        <span
          className={cn(
            'block h-full rounded-full transition-[width]',
            close ? 'bg-lume' : 'bg-ink-3',
          )}
          style={{ width: `${(fill * 100).toFixed(1)}%` }}
        />
      </span>
      <span className={cn('font-mono text-[11px] tnum', close ? 'text-lume' : 'text-ink-3')}>
        {formatMoney(fromCents(Math.max(gap, 0)), currency)}
      </span>
    </span>
  )
}
