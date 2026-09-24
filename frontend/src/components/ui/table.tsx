import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Data table in a horizontally scrolling wrapper, so wide tables never widen the page. */
export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full caption-bottom border-collapse text-[13px]', className)} {...props} />
    </div>
  )
}

/** Table header section. */
export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('[&_tr]:border-b [&_tr]:border-hairline', className)} {...props} />
}

/** Table body section. */
export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

/** Table row; set data-clickable to get the pointer cursor and hover tint. */
export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn('border-b border-hairline transition-colors data-[clickable=true]:cursor-pointer data-[clickable=true]:hover:bg-raised/60', className)}
      {...props}
    />
  )
}

/** Header cell in the small uppercase mono style. */
export function TH({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn('h-8 px-3 text-left align-middle font-mono text-[10px] font-medium tracking-[0.13em] text-ink-3 uppercase', className)}
      {...props}
    />
  )
}

/** Body cell. */
export function TD({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3 py-2 align-middle', className)} {...props} />
}
