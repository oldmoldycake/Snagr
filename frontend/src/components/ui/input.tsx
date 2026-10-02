import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Styled text input; forwards its ref to the native input. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'h-8 w-full rounded-sm border border-hairline-field bg-well px-2.5 text-base sm:text-[14px] text-ink placeholder:text-ink-placeholder',
        'focus:border-lume/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-lume/60',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
