import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, ListFilter, MoreHorizontal, Pencil, Play, Trash2 } from 'lucide-react'
import type { ItemSummary, PriceDrop } from '@/api/types'
import { Sparkline } from '@/components/charts/Sparkline'
import { SnaggedBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MeterToTarget } from '@/components/ui/meter'
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

export interface WatchListProps {
  items: ItemSummary[]
  /** newest recent drop per item id — rendered as an inline ▼ chip */
  drops?: Map<number, PriceDrop>
  showCategory?: boolean
  /** rows expand to show the item's tracked listings inline */
  expandable?: boolean
  /** enables the per-row kebab (run / edit / delete) */
  onEdit?: (item: ItemSummary) => void
  onDelete?: (item: ItemSummary) => void
  onRun?: (item: ItemSummary) => void
  className?: string
}

/** Effective target: the watch's per-user override, falling back to the item's. */
export function effectiveTarget(item: ItemSummary): string | null {
  return item.watch.target_price ?? item.target_price
}

/** Sort for the hunt: in-range first, then by how close the price is to target. */
export function sortByDistanceToTarget(items: ItemSummary[]): ItemSummary[] {
  const ratio = (item: ItemSummary): number => {
    const best = toCents(item.best_price)
    const target = toCents(effectiveTarget(item))
    if (best == null || target == null || target <= 0) return Number.POSITIVE_INFINITY
    return (best - target) / target
  }
  return [...items].sort((a, b) => {
    if (a.target_met !== b.target_met) return a.target_met ? -1 : 1
    const diff = ratio(a) - ratio(b)
    if (diff !== 0) return diff
    return a.name.localeCompare(b.name)
  })
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

function DropChip({ drop }: { drop: PriceDrop }) {
  const pct = Math.abs(Number(drop.pct_change))
  if (!Number.isFinite(pct)) return null
  const fresh = Date.now() - new Date(drop.checked_at).getTime() < 86_400_000
  return (
    <span className="shrink-0 rounded-full border border-drop/30 bg-drop-dim px-1.5 py-px font-mono text-[10px] text-drop tnum">
      <span aria-hidden>▼</span> {pct.toFixed(1)}%{fresh ? ' today' : ''}
    </span>
  )
}

export function WatchList({
  items,
  drops,
  showCategory,
  expandable,
  onEdit,
  onDelete,
  onRun,
  className,
}: WatchListProps) {
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

  const columnCount = 6 + (expandable ? 1 : 0) + (hasActions ? 1 : 0)

  return (
    <Table className={className}>
      <THead>
        <TR>
          {expandable ? <TH className="w-8" /> : null}
          <TH>Item</TH>
          <TH className="hidden md:table-cell">Trend</TH>
          <TH className="text-right">Best</TH>
          <TH className="hidden text-right md:table-cell">Target</TH>
          <TH className="text-right">To target</TH>
          <TH className="hidden text-right sm:table-cell">Checked</TH>
          {hasActions ? <TH className="w-10" /> : null}
        </TR>
      </THead>
      <TBody>
        {items.map((item) => {
          const isExpanded = expanded.has(item.id)
          const drop = drops?.get(item.id)
          return (
            <Fragment key={item.id}>
              <TR
                data-clickable="true"
                onClick={() => navigate(`/items/${item.id}`)}
                className={cn(
                  'border-l-2 border-l-transparent',
                  item.target_met && 'border-l-drop bg-linear-to-r from-drop-dim to-transparent to-60%',
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
                    {showCategory ? (
                      <span className="hidden shrink-0 font-mono text-[10.5px] text-ink-3 md:inline">
                        {item.category_name}
                      </span>
                    ) : null}
                    <CriteriaHint item={item} />
                    {drop && !item.target_met ? <DropChip drop={drop} /> : null}
                  </div>
                </TD>
                <TD className="hidden md:table-cell">
                  <Sparkline data={item.spark} width={80} height={22} />
                </TD>
                <TD
                  className={cn(
                    'text-right font-mono font-semibold tnum',
                    item.target_met ? 'text-drop' : 'text-ink',
                    item.best_price == null && 'font-normal text-ink-3',
                  )}
                >
                  {formatMoney(item.best_price, item.currency)}
                </TD>
                <TD className="hidden text-right font-mono text-ink-3 tnum md:table-cell">
                  {formatMoney(effectiveTarget(item), item.currency)}
                </TD>
                <TD className="text-right">
                  {item.target_met ? (
                    <SnaggedBadge />
                  ) : item.active_listing_count === 0 ? (
                    <span className="font-mono text-[11px] text-ink-3">no listings yet</span>
                  ) : (
                    <MeterToTarget best={item.best_price} target={effectiveTarget(item)} currency={item.currency} />
                  )}
                </TD>
                <TD className="hidden text-right font-mono text-xs whitespace-nowrap text-ink-3 sm:table-cell">
                  {relativeTime(item.last_checked_at)}
                </TD>
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
