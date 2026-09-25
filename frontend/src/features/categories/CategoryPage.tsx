import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Pencil } from 'lucide-react'
import {
  deleteItem,
  getCategoryPriceChange,
  listCategories,
  listItems,
  listSites,
} from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemStatusFilter, ItemSummary } from '@/api/types'
import { RangeSelector, useRangeParam } from '@/components/charts/RangeSelector'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { EditItemDialog } from '@/features/items/EditItemDialog'
import { sortByDistanceToTarget, WatchList } from '@/features/items/WatchList'
import { HuntButton } from '@/features/activity/HuntButton'
import { useJobs } from '@/features/activity/JobsProvider'
import { CategoryChangeChart } from './CategoryChangeChart'
import { CategoryChips } from './CategoryChips'
import { EditCategoryDialog } from './EditCategoryDialog'
import { EditSitesDialog } from './EditSitesDialog'

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'snagged', label: 'In range' },
  { value: 'above_target', label: 'Hunting' },
  { value: 'no_listings', label: 'No listings' },
] as const satisfies readonly { value: ItemStatusFilter; label: string }[]

/**
 * One category's page: its change chart and the watches in it, filterable by
 * status, site and search.
 */
export function CategoryPage() {
  const { slug = '' } = useParams()
  const [range, setRange] = useRangeParam()
  const [status, setStatus] = useState<ItemStatusFilter>('all')
  const [siteFilter, setSiteFilter] = useState<number | undefined>(undefined)
  const [search, setSearch] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  const [editSitesOpen, setEditSitesOpen] = useState(false)
  const [editSitesSession, setEditSitesSession] = useState(0)
  // The last item picked for editing stays set after close, so the dialog
  // stays mounted through its exit animation; the session remounts it fresh
  // on every open.
  const [editingItem, setEditingItem] = useState<ItemSummary | null>(null)
  const [editItemOpen, setEditItemOpen] = useState(false)
  const [editItemSession, setEditItemSession] = useState(0)
  const [deletingItem, setDeletingItem] = useState<ItemSummary | null>(null)
  const queryClient = useQueryClient()
  const { enqueue } = useJobs()

  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const category = categories.data?.data.find((c) => c.slug === slug)

  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  const linkedSites = useMemo(
    () => sites.data?.data.filter((s) => category?.site_ids.includes(s.id)) ?? [],
    [sites.data, category],
  )

  const items = useQuery({
    queryKey: qk.items({
      category_id: category?.id,
      site_id: siteFilter,
      range,
      status,
      search: search || undefined,
    }),
    queryFn: () =>
      listItems({
        category_id: category!.id,
        site_id: siteFilter,
        range,
        status,
        search: search || undefined,
      }),
    enabled: category != null,
    placeholderData: keepPreviousData,
  })

  const change = useQuery({
    queryKey: qk.categoryChange(category?.id ?? 0, range),
    queryFn: () => getCategoryPriceChange(category!.id, range),
    enabled: category != null,
    placeholderData: keepPreviousData,
  })

  const removeItem = useMutation({
    mutationFn: (item: ItemSummary) => deleteItem(item.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      setDeletingItem(null)
    },
  })

  if (categories.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  // the category is found in the list, so only a list that loaded can say it isn't there
  if (categories.isError) {
    return (
      <ErrorState
        title="Couldn't load this category"
        error={categories.error}
        onRetry={() => void categories.refetch()}
        retrying={categories.isFetching}
      />
    )
  }

  if (!category) {
    return <EmptyState title="Category not found" description="It may have been renamed or deleted." />
  }

  const rows = sortByDistanceToTarget(items.data?.data ?? [])
  const openEditSites = () => {
    setEditSitesSession((n) => n + 1)
    setEditSitesOpen(true)
  }

  return (
    <div className="space-y-5">
      <CategoryChips activeSlug={slug} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.03em] text-ink">
              {category.name}
            </h1>
            <Button variant="ghost" size="iconSm" aria-label="Edit category" onClick={() => setEditOpen(true)}>
              <Pencil />
            </Button>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {linkedSites.length === 0 ? (
              <span className="text-xs text-warn">
                <span aria-hidden>⚠</span> No sites linked — the agent has nowhere to search. Edit the
                category to link sites.
              </span>
            ) : (
              linkedSites.map((site) => (
                <Badge key={site.id} variant="muted" className="font-mono">
                  {site.name}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <HuntButton scope="category" scopeId={category.id} label="Hunt this category" size="sm" />
          {/* a category with no sites can't take new items from the UI: the hunter would have nowhere to look */}
          {linkedSites.length === 0 ? (
            <Button variant="warn" size="sm" onClick={openEditSites}>
              Link sites
            </Button>
          ) : (
            <AddItemDialog categoryId={category.id} categoryName={category.name} />
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <RangeSelector value={range} onChange={setRange} />
        <Segmented
          options={STATUS_FILTERS}
          value={status}
          onChange={setStatus}
          ariaLabel="Status filter"
        />
        {linkedSites.length > 1 ? (
          <Select
            ariaLabel="Filter by site"
            className="h-7 text-xs"
            value={siteFilter != null ? String(siteFilter) : 'all'}
            onValueChange={(v) => setSiteFilter(v === 'all' ? undefined : Number(v))}
            options={[
              { value: 'all', label: 'All sites' },
              ...linkedSites.map((site) => ({ value: String(site.id), label: site.name })),
            ]}
          />
        ) : null}
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter items…"
          className="h-7 max-w-44 text-xs"
          aria-label="Filter items"
        />
      </div>

      <Card className={cn(items.isFetching && 'opacity-60')}>
        {items.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : items.isError ? (
          <ErrorState
            className="m-4 border-0"
            title="Couldn't load the items"
            error={items.error}
            onRetry={() => void items.refetch()}
            retrying={items.isFetching}
          />
        ) : rows.length === 0 && status === 'all' && !search ? (
          <EmptyState
            className="m-4 border-0"
            title="Add an item to start tracking"
            description={`Give it a name and a target price — the agent will search ${
              linkedSites.length > 0 ? linkedSites.map((s) => s.name).join(', ') : "this category's sites"
            } for listings.`}
            action={
              category.site_ids.length === 0 ? (
                <Button variant="warn" size="sm" onClick={openEditSites}>
                  Link sites
                </Button>
              ) : (
                <AddItemDialog categoryId={category.id} categoryName={category.name} />
              )
            }
          />
        ) : rows.length === 0 ? (
          <p className="px-4 py-6 text-[13px] text-ink-3">No items match this filter.</p>
        ) : (
          <>
            <WatchList
              items={rows}
              expandable
              onEdit={(item) => {
                setEditingItem(item)
                setEditItemSession((n) => n + 1)
                setEditItemOpen(true)
              }}
              onDelete={(item) => setDeletingItem(item)}
              onHunt={(item) => enqueue({ kind: 'hunt', scope: 'item', scope_id: item.id })}
            />
            <div className="border-t border-hairline bg-well px-4 py-2 font-mono text-[11px] text-ink-3">
              {rows.length} {rows.length === 1 ? 'item' : 'items'} · sorted by distance to target
            </div>
          </>
        )}
      </Card>

      {rows.length > 0 ? (
        <Card className={cn(change.isFetching && 'opacity-60')}>
          <CardHeader>
            <CardTitle>Price change</CardTitle>
            <span className="font-mono text-[11px] text-ink-3">
              {range === 'all' ? 'all time' : `last ${range}`}
            </span>
          </CardHeader>
          <CardBody className="px-2">
            {change.isLoading ? (
              <Skeleton className="m-2 h-32" />
            ) : (
              <CategoryChangeChart items={change.data?.items ?? []} />
            )}
          </CardBody>
        </Card>
      ) : null}

      <EditSitesDialog
        key={`sites-${editSitesSession}`}
        category={category}
        open={editSitesOpen}
        onOpenChange={setEditSitesOpen}
      />
      <EditCategoryDialog
        key={category.id}
        category={category}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
      {editingItem ? (
        <EditItemDialog key={`item-${editItemSession}`} item={editingItem} open={editItemOpen} onOpenChange={setEditItemOpen} />
      ) : null}
      <ConfirmDialog
        open={deletingItem != null}
        onOpenChange={(open) => {
          if (!open) setDeletingItem(null)
        }}
        title="Delete item"
        description={
          deletingItem ? `“${deletingItem.name}” and its price history will be permanently removed.` : ''
        }
        confirmLabel="Delete item"
        pending={removeItem.isPending}
        onConfirm={() => {
          if (deletingItem) removeItem.mutate(deletingItem)
        }}
      />
    </div>
  )
}
