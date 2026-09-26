import type { Category, ItemSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { AddItemDialog } from '@/features/items/AddItemDialog'

/** A category holding none of the caller's items, as one line: its sites and a way in. */
export function CategoryRow({
  category,
  siteNames,
  isNew,
  edge,
  onEditSites,
  onAdded,
}: {
  category: Category
  siteNames: string[]
  /** the category the caller just created */
  isNew?: boolean
  /** outline it once, when it has just appeared */
  edge?: boolean
  onEditSites: (category: Category) => void
  onAdded: (item: ItemSummary) => void
}) {
  const noSites = category.site_ids.length === 0
  return (
    <div
      id={`shelf-${category.id}`}
      data-edge={edge || undefined}
      className={cn(
        'flex min-h-11 scroll-mt-11 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border py-[9px] pr-2.5 pl-[38px] data-edge:animate-strike-edge max-sm:pl-3',
        isNew ? 'border-lume/40' : 'border-hairline',
      )}
    >
      <span className="font-display text-[17px] leading-none font-semibold tracking-[0.06em] text-ink-2 uppercase">
        {category.name}
      </span>
      <span
        className={cn(
          'min-w-40 flex-1 font-mono text-[11px]',
          noSites ? 'text-warn' : isNew ? 'text-lume' : 'text-ink-3',
        )}
      >
        {noSites
          ? "⚠ no sites. Snagr can't search here."
          : `${isNew ? 'new' : 'none of yours'} · searching ${siteNames.join(', ')}`}
      </span>
      {noSites ? (
        <Button variant="warn" size="sm" onClick={() => onEditSites(category)}>
          Link sites
        </Button>
      ) : (
        <AddItemDialog
          categoryId={category.id}
          categoryName={category.name}
          variant="default"
          label={`Add item to ${category.name}`}
          className="max-sm:size-9 max-sm:px-0 max-sm:text-base"
          trigger={
            <>
              <span className="max-sm:hidden">＋ Add item</span>
              <span aria-hidden className="sm:hidden">
                ＋
              </span>
            </>
          }
          onAdded={onAdded}
        />
      )}
    </div>
  )
}
