import type { KeyboardEvent } from 'react'
import { cn } from '@/lib/cn'
import { useTrack } from '@/lib/useTrack'

const STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }

/**
 * The one segmented control: mono caps on a well, with one raised plate that
 * tracks the checked option (the nav's "Reticle Track" motion). Used for time
 * ranges, chart tabs, status filters, and the selection-mode picker. A null
 * value checks nothing — the check-interval picker's "instance default".
 *
 * A radio group: the checked option is the one Tab stop, and the arrow keys
 * (Home, End) move and select. The root scrolls sideways, so a picker wider
 * than a phone's card scrolls inside itself instead of being clipped.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: readonly { value: T; label: string }[]
  value: T | null
  onChange: (value: T) => void
  ariaLabel: string
  className?: string
}) {
  const { hostRef, markerRef } = useTrack<HTMLDivElement>('[aria-checked="true"]', value)
  const tabStop = Math.max(0, options.findIndex((o) => o.value === value))

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const radios = [...e.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]')]
    const i = radios.indexOf(e.target as HTMLElement)
    if (i < 0) return
    let next: number
    if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = radios.length - 1
    else if (e.key in STEP) next = (i + STEP[e.key] + radios.length) % radios.length
    else return
    e.preventDefault()
    radios[next].focus()
    onChange(options[next].value)
  }

  return (
    <div
      className={cn(
        'inline-flex max-w-full min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
        className,
      )}
    >
      <div
        ref={hostRef}
        role="radiogroup"
        aria-label={ariaLabel}
        onKeyDown={onKeyDown}
        className="relative flex min-w-full flex-none gap-0.5 rounded-sm border border-hairline bg-well p-0.5"
      >
        <span ref={markerRef} aria-hidden className="seg-plate" />
        {options.map((o, i) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            tabIndex={i === tabStop ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              'seg-option relative flex h-[22px] flex-[1_0_auto] items-center justify-center rounded-[3px] px-2 font-mono text-[11px] tracking-[0.04em] whitespace-nowrap uppercase transition-colors focus-visible:-outline-offset-2 max-sm:h-[26px]',
              value === o.value ? 'text-ink' : 'text-ink-3 hover:text-ink-2',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}
