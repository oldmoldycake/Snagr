import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, ListFilter, MoreHorizontal, Pencil, Play, Trash2 } from 'lucide-react'
import type { ItemSummary } from '@/api/types'
import { Sparkline } from '@/components/charts/Sparkline'
import { DeltaText } from '@/components/charts/DeltaText'
import { SnaggedBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'
import { formatMoney, toCents } from '@/lib/money'
import { relativeTime } from '@/lib/time'
import { ItemListingsPanel } from './ItemListingsPanel'

export interface ItemsTableProps {
  items: ItemSummary[]
  showCategory?: boolean
  showListings?: boolean
  showLastChecked?: boolean
  /** rows expand to show the item's tracked listings inline */
  expandable?: boolean
  /** enables the per-row kebab (run / edit / delete) */
  onEdit?: (item: ItemSummary) => void
  onDelete?: (item: ItemSummary) => void
  onRun?: (item: ItemSummary) => void
  className?: string
}

/** Δ of best price vs effective target, as a signed percent. */
function deltaToTarget(item: ItemSummary): number | null {
  const best = toCents(item.best_price)
  const target = toCents(item.watch.target_price ?? item.target_price)
  if (best == null || target == null || target === 0) return null
  return ((best - target) / target) * 100
}

function CriteriaHint({ item }: { item: ItemSummary }) {
  if (!item.criteria) return null
  const mode = item.selection_mode === 'best_match' ? 'Best match' : 'Cheapest'
  return (
    <SimpleTooltip content={<span className="block max-w-64">{`${mode} — “${item.criteria}”`}</span>}>
      <ListFilter aria-label="Has criteria" className="size-3.5 shrink-0 text-ink-3" />
    </SimpleTooltip>
  )
}

export function ItemsTable({
  items,
  showCategory,
  showListings,
  showLastChecked,
  expandable,
  onEdit,
  onDelete,
  onRun,
  className,
}: ItemsTableProps) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const hasActions = Boolean(onEdit || onDelete || onRun)

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const columnCount =
    5 +
    (expandable ? 1 : 0) +
    (showCategory ? 1 : 0) +
    (showListings ? 1 : 0) +
    (showLastChecked ? 1 : 0) +
    (hasActions ? 1 : 0)

  return (
    <Table className={className}>
      <THead>
        <TR>
          {expandable ? <TH className="w-8" /> : null}
          <TH>Item</TH>
          {showCategory ? <TH>Category</TH> : null}
          <TH className="text-right">Best price</TH>
          <TH className="text-right">Target</TH>
          <TH className="text-right">Δ target</TH>
          {showListings ? <TH className="text-right">Listings</TH> : null}
          <TH>Trend</TH>
          {showLastChecked ? <TH>Checked</TH> : null}
          {hasActions ? <TH className="w-10" /> : null}
        </TR>
      </THead>
      <TBody>
        {items.map((item) => {
          const delta = deltaToTarget(item)
          const isExpanded = expanded.has(item.id)
          return (
            <Fragment key={item.id}>
              <TR
                data-clickable="true"
                onClick={() => navigate(`/items/${item.id}`)}
                className={cn(
                  'border-l-2 border-l-transparent',
                  item.target_met && 'border-l-drop',
                  isExpanded && 'border-b-0',
                )}
              >
                {expandable ? (
                  <TD onClick={(e) => e.stopPropagation()} className="pr-0">
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-label={`${isExpanded ? 'Collapse' : 'Expand'} listings for ${item.name}`}
                      className="flex size-5 items-center justify-center rounded-sm text-ink-3 hover:bg-raised hover:text-ink"
                      onClick={() => toggleExpand(item.id)}
                    >
                      {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    </button>
                  </TD>
                ) : null}
                <TD>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">{item.name}</span>
                    <CriteriaHint item={item} />
                    {item.target_met ? <SnaggedBadge /> : null}
                    {item.active_listing_count === 0 ? (
                      <span className="text-xs text-ink-3">no listings yet</span>
                    ) : null}
                  </div>
                </TD>
                {showCategory ? <TD className="text-ink-2">{item.category_name}</TD> : null}
                <TD className="text-right font-mono text-ink tnum">
                  {formatMoney(item.best_price, item.currency)}
                </TD>
                <TD className="text-right font-mono text-ink-2 tnum">
                  {formatMoney(item.watch.target_price ?? item.target_price, item.currency)}
                </TD>
                <TD className="text-right">
                  <DeltaText value={delta == null ? null : delta.toFixed(1)} />
                </TD>
                {showListings ? (
                  <TD className="text-right font-mono text-ink-2 tnum">{item.active_listing_count}</TD>
                ) : null}
                <TD>
                  <Sparkline data={item.spark} />
                </TD>
                {showLastChecked ? (
                  <TD className="text-xs whitespace-nowrap text-ink-3">{relativeTime(item.last_checked_at)}</TD>
                ) : null}
                {hasActions ? (
                  <TD onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="iconSm" aria-label={`Actions for ${item.name}`}>
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {onRun ? (
                          <DropdownMenuItem onSelect={() => onRun(item)}>
                            <Play /> Run agent on this item
                          </DropdownMenuItem>
                        ) : null}
                        {onEdit ? (
                          <DropdownMenuItem onSelect={() => onEdit(item)}>
                            <Pencil /> Edit
                          </DropdownMenuItem>
                        ) : null}
                        {onDelete ? (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem className="text-rise" onSelect={() => onDelete(item)}>
                              <Trash2 /> Delete
                            </DropdownMenuItem>
                          </>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TD>
                ) : null}
              </TR>
              {isExpanded ? (
                <TR className="border-l-2 border-l-transparent bg-page/40">
                  <TD colSpan={columnCount} className="py-1 pl-11">
                    <ItemListingsPanel itemId={item.id} />
                  </TD>
                </TR>
              ) : null}
            </Fragment>
          )
        })}
      </TBody>
    </Table>
  )
}
