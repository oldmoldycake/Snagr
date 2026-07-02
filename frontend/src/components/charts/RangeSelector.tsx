import { useSearchParams } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { RANGE_LABELS, TIME_RANGES, type TimeRange } from '@/lib/time'

/** Range state lives in the URL (?range=90d) so links share it. */
export function useRangeParam(): [TimeRange, (r: TimeRange) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('range')
  const range: TimeRange = TIME_RANGES.includes(raw as TimeRange) ? (raw as TimeRange) : '30d'
  const setRange = (r: TimeRange) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('range', r)
        return next
      },
      { replace: true },
    )
  }
  return [range, setRange]
}

export function RangeSelector({
  value,
  onChange,
  className,
}: {
  value: TimeRange
  onChange: (r: TimeRange) => void
  className?: string
}) {
  return (
    <div
      role="group"
      aria-label="Time range"
      className={cn('inline-flex overflow-hidden rounded-sm border border-hairline', className)}
    >
      {TIME_RANGES.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={value === r}
          onClick={() => onChange(r)}
          className={cn(
            'px-2.5 py-1 font-mono text-xs transition-colors',
            value === r ? 'bg-raised text-ink' : 'bg-transparent text-ink-3 hover:text-ink-2',
          )}
        >
          {RANGE_LABELS[r]}
        </button>
      ))}
    </div>
  )
}
