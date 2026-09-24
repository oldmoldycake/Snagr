import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Bordered surface panel. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('overflow-hidden rounded-lg border border-hairline bg-surface', className)}
      {...props}
    />
  )
}

/** Card top row — title on the left, actions on the right. */
export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center justify-between px-4 pt-3.5 pb-2', className)} {...props} />
}

/** Card heading in the uppercase display face. */
export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        'font-display text-[15px] font-semibold tracking-[0.12em] text-ink-2 uppercase',
        className,
      )}
      {...props}
    />
  )
}

/** Padded card content area. */
export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 pb-4', className)} {...props} />
}
