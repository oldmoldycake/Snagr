import { cn } from '@/lib/cn'
import type { PageMeta } from '@/api/types'

/** Quiet mono pager. Renders nothing when everything fits on one page. */
export function Pagination({
  meta,
  onPage,
  className,
}: {
  meta: PageMeta
  onPage: (page: number) => void
  className?: string
}) {
  const pages = Math.max(1, Math.ceil(meta.total / meta.per_page))
  if (pages <= 1) return null

  const btn =
    'flex h-5 w-6 items-center justify-center rounded-[3px] border border-hairline font-mono text-[11px] text-ink-2 hover:border-ink-3 hover:text-ink disabled:pointer-events-none disabled:opacity-40'

  return (
    <nav aria-label="Pagination" className={cn('flex items-center gap-2', className)}>
      <span className="font-mono text-[11px] text-ink-3 tnum">
        {meta.page} / {pages}
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          className={btn}
          disabled={meta.page <= 1}
          onClick={() => onPage(meta.page - 1)}
          aria-label="Previous page"
        >
          ‹
        </button>
        <button
          type="button"
          className={btn}
          disabled={meta.page >= pages}
          onClick={() => onPage(meta.page + 1)}
          aria-label="Next page"
        >
          ›
        </button>
      </div>
    </nav>
  )
}
