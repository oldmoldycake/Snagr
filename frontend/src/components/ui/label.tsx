import type { LabelHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Form field label in the small mono style. */
export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        'mb-1.5 block font-mono text-[12px] font-medium text-ink-3',
        className,
      )}
      {...props}
    />
  )
}
