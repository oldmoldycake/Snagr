import type { LabelHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        'mb-1.5 block font-mono text-[10px] font-medium tracking-[0.14em] text-ink-3 uppercase',
        className,
      )}
      {...props}
    />
  )
}
