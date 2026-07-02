import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-medium leading-4',
  {
    variants: {
      variant: {
        default: 'bg-raised text-ink-2 border border-hairline',
        snagged: 'bg-drop/15 text-drop border border-drop/40',
        rise: 'bg-rise/10 text-rise border border-rise/40',
        warn: 'bg-warn/10 text-warn border border-warn/40',
        accent: 'bg-accent/15 text-accent border border-accent/40',
        muted: 'bg-transparent text-ink-3 border border-hairline',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

/** The Snagged state — target hit. Always carries the crosshair glyph. */
export function SnaggedBadge({ className }: { className?: string }) {
  return (
    <Badge variant="snagged" className={className}>
      <span aria-hidden>⌖</span> Snagged
    </Badge>
  )
}
