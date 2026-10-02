import { Link } from 'react-router-dom'
import type { Category, ItemSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { useSession } from '@/features/auth/useSession'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { ShelfMenu } from './CategoryShelf'

/** A category holding none of the caller's items, as one line: its sites, a way in and its ⋯ menu. */
export function CategoryRow({
  category,
  siteNames,
  isNew,
  edge,
  onEditSites,
  onRename,
  onAdded,
}: {
  category: Category
  siteNames: string[]
  /** the category the caller just created */
  isNew?: boolean
  /** outline it once, when it has just appeared */
  edge?: boolean
  onEditSites: (category: Category) => void
  onRename: (category: Category) => void
  onAdded: (item: ItemSummary) => void
}) {
  const noSites = category.site_ids.length === 0
  // categories are shared, so only an admin links their sites
  const isAdmin = useSession().data?.role === 'admin'
  return (
    <div
      id={`shelf-${category.id}`}
      data-edge={edge || undefined}
      className={cn(
        'flex min-h-11 scroll-mt-11 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border py-[9px] pr-2.5 pl-[38px] data-edge:animate-strike-edge max-sm:pl-3',
        isNew ? 'border-lume/40' : 'border-hairline',
      )}
    >
      <Link
        to={`/categories/${category.slug}`}
        className="min-w-0 font-display text-[17px] leading-none font-semibold tracking-[0.06em] wrap-anywhere text-ink-2 uppercase hover:text-lume"
      >
        {category.name}
      </Link>
      <span
        className={cn(
          'min-w-40 flex-1 font-mono text-[12px]',
          noSites ? 'text-warn' : isNew ? 'text-lume' : 'text-ink-3',
        )}
      >
        {noSites
          ? "⚠ no sites. Snagr can't search here."
          : `${isNew ? 'new' : 'none of yours'} · searching ${siteNames.join(', ')}`}
      </span>
      <div className="flex shrink-0 items-center gap-1">
        {noSites ? (
          isAdmin ? (
            <Button variant="warn" size="sm" onClick={() => onEditSites(category)}>
              Link sites
            </Button>
          ) : null
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
        <ShelfMenu category={category} hits={0} siteNames={siteNames} onEditSites={onEditSites} onRename={onRename} />
      </div>
    </div>
  )
}
