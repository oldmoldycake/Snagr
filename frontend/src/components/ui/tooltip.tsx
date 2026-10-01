import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** Shared tooltip context — Radix Tooltip.Provider; mount once near the root. */
export const TooltipProvider = TooltipPrimitive.Provider

/**
 * Tooltip around a single child — Radix Tooltip with a 300 ms delay — that a
 * click or tap also toggles: Radix opens only on hover and focus, and a touch
 * screen has neither. The trigger is a real button so keyboard users reach it;
 * pass `asChild` when the child already is one (it must not run an action of
 * its own, or the tip would hide what the press did). The press stays inside
 * the trigger, so a tip in a clickable row doesn't also toggle the row.
 */
export function SimpleTooltip({
  content,
  children,
  label,
  asChild = false,
  side,
  className,
}: {
  content: ReactNode
  children: ReactNode
  /** Accessible name for the wrapping button when `children` has no text of its own. */
  label?: string
  asChild?: boolean
  side?: ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>['side']
  className?: string
}) {
  const [open, setOpen] = useState(false)
  // Radix closes an open tip on pointerdown, so by click time `open` no longer
  // says whether this press meant to open it or to close it
  const openAtPress = useRef<boolean | null>(null)

  return (
    <TooltipPrimitive.Root delayDuration={300} open={open} onOpenChange={setOpen}>
      <TooltipPrimitive.Trigger
        asChild
        onPointerDown={() => {
          openAtPress.current = open
        }}
        onClick={(e) => {
          // preventDefault keeps Radix from closing it again on the same click
          e.preventDefault()
          e.stopPropagation()
          setOpen(!(openAtPress.current ?? open))
          openAtPress.current = null
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') e.stopPropagation()
        }}
      >
        {asChild ? (
          children
        ) : (
          <button type="button" aria-label={label} className="inline-flex shrink-0 rounded-full">
            {children}
          </button>
        )}
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={4}
          className={cn(
            'z-50 rounded-sm border border-hairline bg-overlay px-2 py-1 text-xs text-ink-2 shadow-lg',
            className,
          )}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
