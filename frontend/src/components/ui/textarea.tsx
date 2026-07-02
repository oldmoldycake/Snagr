import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, rows = 3, ...props }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        'w-full resize-y rounded-sm border border-hairline bg-page px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-3',
        'focus:border-accent/60 focus:outline-none',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'
