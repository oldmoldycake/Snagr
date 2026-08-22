import { useSearchParams } from 'react-router-dom'
import { Segmented } from '@/components/ui/segmented'
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
    <Segmented
      options={TIME_RANGES.map((r) => ({ value: r, label: RANGE_LABELS[r] }))}
      value={value}
      onChange={onChange}
      ariaLabel="Time range"
      className={className}
    />
  )
}
