import { useState } from 'react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { cn } from '@/lib/cn'
import { formatDateTime, relativeTime } from '@/lib/time'

/**
 * `5m ago`, with the exact time in a tooltip — "6mo ago" alone can't say
 * which day. Opens on hover and keyboard focus like any tooltip, and on tap
 * too, which Radix leaves out because touch has no hover.
 */
export function RelativeTime({ iso, className }: { iso: string | null | undefined; className?: string }) {
  const [open, setOpen] = useState(false)
  const text = relativeTime(iso)
  if (!iso || text === '—') return <span className={className}>{text}</span>
  return (
    <TooltipPrimitive.Root open={open} onOpenChange={setOpen} delayDuration={300}>
      <TooltipPrimitive.Trigger asChild>
        <time
          dateTime={iso}
          tabIndex={0}
          className={cn('cursor-default', className)}
          onClick={(event) => {
            // the tap is for the time, not a row or link it sits in. Open rather
            // than toggle: a tap's focus may already have opened it, and
            // preventing the default keeps Radix's click-to-close from undoing
            // that. A tap anywhere else closes it.
            event.preventDefault()
            event.stopPropagation()
            setOpen(true)
          }}
        >
          {text}
        </time>
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={4}
          className="z-50 rounded-sm border border-hairline bg-overlay px-2 py-1 font-mono text-xs text-ink-2 shadow-lg tnum"
        >
          {formatDateTime(iso)}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
