import { cn } from '@/lib/cn'

/**
 * Signed change with direction glyph. `polarity` picks which sign is good:
 * 'price' — down is good (green); 'growth' — up is good; 'neutral' — plain
 * ink for metrics with no goodness axis.
 */
export function DeltaText({
  value,
  suffix = '%',
  polarity = 'price',
  className,
}: {
  value: string | number | null | undefined
  suffix?: string
  polarity?: 'price' | 'growth' | 'neutral'
  className?: string
}) {
  if (value == null) return <span className={cn('text-ink-3', className)}>—</span>
  const n = Number(value)
  if (!Number.isFinite(n)) return <span className={cn('text-ink-3', className)}>—</span>

  const glyph = n < 0 ? '▼' : n > 0 ? '▲' : '—'
  let color = 'text-ink-3'
  if (n !== 0 && polarity === 'price') color = n < 0 ? 'text-drop' : 'text-rise'
  if (n !== 0 && polarity === 'growth') color = n > 0 ? 'text-drop' : 'text-rise'

  const magnitude = Math.abs(n)
  const text = suffix === '%' ? magnitude.toFixed(1) : String(magnitude)

  return (
    <span className={cn('font-mono text-xs tnum', color, className)}>
      <span aria-hidden>{glyph}</span> {text}
      {suffix}
    </span>
  )
}
