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
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { EditItemDialog } from '@/features/items/EditItemDialog'
import { ItemsTable } from '@/features/items/ItemsTable'
import { RunButton } from '@/features/runs/RunButton'
import { useRunEvents } from '@/features/runs/RunEventsProvider'
import { CategoryChangeChart } from './CategoryChangeChart'
import { EditCategoryDialog } from './EditCategoryDialog'

const STATUS_FILTERS: { value: ItemStatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'snagged', label: 'Snagged' },
  { value: 'above_target', label: 'Above target' },
  { value: 'no_listings', label: 'No listings' },
]

export function CategoryPage() {
  const { slug = '' } = useParams()
  const [range, setRange] = useRangeParam()
  const [status, setStatus] = useState<ItemStatusFilter>('all')
  const [siteFilter, setSiteFilter] = useState<number | undefined>(undefined)
  const [search, setSearch] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<ItemSummary | null>(null)
  const queryClient = useQueryClient()
  const { trigger } = useRunEvents()

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

  if (!category) {
    return <EmptyState title="Category not found" description="It may have been renamed or deleted." />
  }

  const rows = items.data?.data ?? []

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-lg font-semibold text-ink">{category.name}</h1>
            <Button variant="ghost" size="iconSm" aria-label="Edit category" onClick={() => setEditOpen(true)}>
              <Pencil />
            </Button>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {linkedSites.length === 0 ? (
              <span className="text-xs text-warn">
                No sites linked — the agent has nowhere to search. Edit the category to link sites.
              </span>
            ) : (
              linkedSites.map((site) => (
                <Badge key={site.id} variant="muted">
                  {site.name}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <RunButton scope="category" scopeId={category.id} label="Run agent on this category" variant="snag" size="sm" />
          <AddItemDialog categoryId={category.id} categoryName={category.name} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <RangeSelector value={range} onChange={setRange} />
        <div role="group" aria-label="Status filter" className="inline-flex overflow-hidden rounded-sm border border-hairline">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={status === f.value}
              onClick={() => setStatus(f.value)}
              className={cn(
                'px-2.5 py-1 text-xs transition-colors',
                status === f.value ? 'bg-raised text-ink' : 'text-ink-3 hover:text-ink-2',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        {linkedSites.length > 1 ? (
          <select
            value={siteFilter ?? ''}
            onChange={(e) => setSiteFilter(e.target.value ? Number(e.target.value) : undefined)}
            aria-label="Filter by site"
            className="h-7 rounded-sm border border-hairline bg-page px-2 text-xs text-ink-2 focus:border-accent/60 focus:outline-none"
          >
            <option value="">All sites</option>
            {linkedSites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
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
        <CardBody className="px-0 pt-1 pb-1">
          {items.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
            </div>
          ) : rows.length === 0 && status === 'all' && !search ? (
            <EmptyState
              className="m-4 border-0"
              title="Add an item to start tracking"
              description={`Give it a name and a target price — the agent will search ${
                linkedSites.length > 0 ? linkedSites.map((s) => s.name).join(', ') : "this category's sites"
              } for listings.`}
              action={<AddItemDialog categoryId={category.id} categoryName={category.name} />}
            />
          ) : rows.length === 0 ? (
            <p className="px-4 py-6 text-[13px] text-ink-3">No items match this filter.</p>
          ) : (
            <ItemsTable
              items={rows}
              expandable
              showListings
              showLastChecked
              onEdit={(item) => setEditingItem(item)}
              onDelete={(item) => {
                if (window.confirm(`Delete “${item.name}” and its price history?`)) {
                  removeItem.mutate(item)
                }
              }}
              onRun={(item) => trigger({ scope: 'item', scope_id: item.id })}
            />
          )}
        </CardBody>
      </Card>

      {rows.length > 0 ? (
        <Card className={cn(change.isFetching && 'opacity-60')}>
          <CardHeader>
            <CardTitle>Price change over {range === 'all' ? 'all time' : `the last ${range}`}</CardTitle>
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

      <EditCategoryDialog
        key={category.id}
        category={category}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
      {editingItem ? (
        <EditItemDialog
          item={editingItem}
          open={editingItem != null}
          onOpenChange={(open) => {
            if (!open) setEditingItem(null)
          }}
        />
      ) : null}
    </div>
  )
}
