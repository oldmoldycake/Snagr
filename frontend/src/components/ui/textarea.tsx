import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Styled multi-line input, three rows by default; forwards its ref to the native textarea. */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, rows = 3, ...props }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        'w-full resize-y rounded-sm border border-hairline-field bg-well px-2.5 py-1.5 text-[14px] text-ink placeholder:text-ink-3',
        'focus:border-lume/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-lume/60',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'
