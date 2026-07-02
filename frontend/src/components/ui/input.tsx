import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'h-8 w-full rounded-sm border border-hairline bg-page px-2.5 text-[13px] text-ink placeholder:text-ink-3',
        'focus:border-accent/60 focus:outline-none',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
