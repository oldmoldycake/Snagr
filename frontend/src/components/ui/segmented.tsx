import { cn } from '@/lib/cn'

/**
 * The one segmented control: mono caps, lume-glow active pill. Used for time
 * ranges, chart tabs, status filters, and the selection-mode picker.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  className?: string
}) {
  return (
    <div role="group" aria-label={ariaLabel} className={cn('inline-flex gap-0.5', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-sm px-2 py-1 font-mono text-[11px] tracking-[0.04em] uppercase transition-colors',
            value === o.value ? 'bg-lume-glow text-lume' : 'text-ink-3 hover:text-ink-2',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
