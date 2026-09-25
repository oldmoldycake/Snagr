import { Fragment } from 'react'
import { cn } from '@/lib/cn'

/**
 * Numbered steps of a short flow, `① Name → ② Sites`. The current step is lume;
 * a finished one shows ✓ in ink-2, never drop-green, because green means a good price.
 */
export function StepPips({
  steps,
  current,
  size = 'sm',
  className,
}: {
  steps: string[]
  /** 1-based index of the step in progress */
  current: number
  /** sm fits a dialog eyebrow; md sits under a page title */
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <ol
      className={cn(
        'flex flex-wrap items-center gap-x-2.5 gap-y-1.5 font-mono font-medium tracking-[0.08em] text-ink-3 uppercase',
        size === 'sm' ? 'text-[10px]' : 'text-[11px]',
        className,
      )}
    >
      {steps.map((label, i) => {
        const step = i + 1
        const done = step < current
        const on = step === current
        return (
          <Fragment key={label}>
            {i > 0 ? (
              <li aria-hidden className="text-ink-3">
                →
              </li>
            ) : null}
            <li
              aria-current={on ? 'step' : undefined}
              className={cn('inline-flex items-center gap-1.5', on && 'text-lume', done && 'text-ink-2')}
            >
              <span
                className={cn(
                  'grid place-items-center rounded-full border tracking-normal',
                  size === 'sm' ? 'size-4 text-[9px]' : 'size-[18px] text-[10px]',
                  on ? 'border-lume' : 'border-hairline-strong',
                )}
              >
                {done ? <span aria-hidden>✓</span> : step}
              </span>
              {label}
              {done ? <span className="sr-only"> (done)</span> : null}
            </li>
          </Fragment>
        )
      })}
    </ol>
  )
}
