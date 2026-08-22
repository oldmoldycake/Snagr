import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { CreateCategoryDialog } from './CreateCategoryDialog'

/**
 * Category filter line — the sidebar's replacement. "All" is the dashboard;
 * a chip is its category page, so the filter state is just the URL.
 */
export function CategoryChips({ activeSlug, className }: { activeSlug?: string; className?: string }) {
  const { data } = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const categories = data?.data ?? []

  const chipClass = (isActive: boolean) =>
    cn(
      'border-b-2 pb-0.5 font-mono text-[11px] whitespace-nowrap transition-colors',
      isActive ? 'border-lume text-ink' : 'border-transparent text-ink-3 hover:text-ink-2',
    )

  return (
    <div className={cn('flex flex-wrap items-baseline gap-x-4 gap-y-1.5', className)}>
      <Link to="/" className={chipClass(activeSlug == null)}>
        All
      </Link>
      {categories.map((category) => (
        <Link
          key={category.id}
          to={`/categories/${category.slug}`}
          className={chipClass(activeSlug === category.slug)}
        >
          {category.name}
          <span className="ml-1 text-ink-3 tnum">{category.item_count}</span>
          {category.snagged_count > 0 ? (
            <span title={`${category.snagged_count} at target`} className="ml-1 text-drop tnum">
              ⌖{category.snagged_count}
            </span>
          ) : null}
        </Link>
      ))}
      <CreateCategoryDialog
        variant="ghost"
        className="h-auto px-1 py-0 text-[11px] text-ink-3"
        trigger={<span>＋ category</span>}
      />
    </div>
  )
}
