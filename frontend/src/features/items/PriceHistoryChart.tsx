import { useMemo } from 'react'
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ListingSeries, PriceHistoryResponse } from '@/api/types'
import { axisTickStyle, chart, seriesColor } from '@/components/charts/chartTheme'
import { TooltipFrame, TooltipRow, tooltipTimeLabel } from '@/components/charts/ChartTooltip'
import { formatMoney } from '@/lib/money'
import { tickFormatterFor, type TimeRange } from '@/lib/time'

const MAX_SERIES = 6

/** Listing title when the agent extracted one, else the site — multiple eBay listings need names. */
function seriesLabel(series: ListingSeries): string {
  const label = series.title ?? series.site_name
  return label.length > 28 ? `${label.slice(0, 27)}…` : label
}

interface PreparedSeries {
  listing: ListingSeries
  color: string
  points: { ts: number; price: number; in_stock: boolean }[]
}

/** Latest price at-or-before ts, step semantics (price holds until next check). */
function priceAt(series: PreparedSeries, ts: number): { price: number; in_stock: boolean } | null {
  let result: { price: number; in_stock: boolean } | null = null
  for (const p of series.points) {
    if (p.ts > ts) break
    result = { price: p.price, in_stock: p.in_stock }
  }
  return result
}

export function PriceHistoryChart({ data, range }: { data: PriceHistoryResponse; range: TimeRange }) {
  const { plotted, foldedCount, rows, yDomain } = useMemo(() => {
    // Stable slot order: listing id ascending — color follows the entity.
    const sorted = [...data.series].sort((a, b) => a.listing_id - b.listing_id)
    const withColors: PreparedSeries[] = sorted.map((s, i) => ({
      listing: s,
      color: seriesColor(i),
      points: s.points
        .map((p) => ({ ts: new Date(p.ts).getTime(), price: Number(p.price), in_stock: p.in_stock }))
        .sort((a, b) => a.ts - b.ts),
    }))

    // >6 listings: plot the 6 with the lowest latest price, fold the rest.
    let plotted = withColors.filter((s) => s.points.length > 0)
    let foldedCount = 0
    if (plotted.length > MAX_SERIES) {
      plotted = [...plotted]
        .sort((a, b) => a.points[a.points.length - 1].price - b.points[b.points.length - 1].price)
        .slice(0, MAX_SERIES)
        .sort((a, b) => a.listing.listing_id - b.listing.listing_id)
      foldedCount = withColors.length - MAX_SERIES
    }

    // Merge on the union of timestamps; carry-forward fills are legal because
    // a price is a step function — it holds until the next check.
    const tsSet = new Set<number>()
    for (const s of plotted) for (const p of s.points) tsSet.add(p.ts)
    const timestamps = [...tsSet].sort((a, b) => a - b)
    const rows = timestamps.map((ts) => {
      const row: Record<string, number | null> = { ts }
      for (const s of plotted) {
        row[`l${s.listing.listing_id}`] = priceAt(s, ts)?.price ?? null
      }
      return row
    })

    const prices = plotted.flatMap((s) => s.points.map((p) => p.price))
    const target = data.target_price != null ? Number(data.target_price) : null
    const min = Math.min(...prices, ...(target != null ? [target] : []))
    const max = Math.max(...prices, ...(target != null ? [target] : []))
    const yDomain: [number, number] = [Math.floor((min * 0.97) / 10) * 10, Math.ceil((max * 1.02) / 10) * 10]

    return { plotted, foldedCount, rows, yDomain }
  }, [data])

  if (plotted.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-[13px] text-ink-3">
        No price history yet — run the agent to check this item's listings.
      </p>
    )
  }

  const target = data.target_price != null ? Number(data.target_price) : null

  return (
    <div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <XAxis
              dataKey="ts"
              type="number"
              domain={['dataMin', 'dataMax']}
              tick={axisTickStyle}
              tickFormatter={tickFormatterFor(range)}
              axisLine={{ stroke: chart.grid }}
              tickLine={false}
              minTickGap={60}
            />
            <YAxis
              domain={yDomain}
              tick={axisTickStyle}
              tickFormatter={(v: number) => `$${Math.round(v)}`}
              axisLine={false}
              tickLine={false}
              width={52}
            />
            <Tooltip
              cursor={{ stroke: chart.inkMuted, strokeDasharray: '3 3' }}
              content={({ active, label }) => {
                if (!active || label == null) return null
                const ts = Number(label)
                return (
                  <TooltipFrame label={tooltipTimeLabel(ts)}>
                    {plotted.map((s) => {
                      const at = priceAt(s, ts)
                      if (!at) return null
                      const notes = [
                        s.listing.title ? s.listing.site_name : null,
                        at.in_stock ? null : 'out of stock',
                      ].filter(Boolean)
                      return (
                        <TooltipRow
                          key={s.listing.listing_id}
                          color={s.color}
                          value={formatMoney(at.price.toFixed(2), data.currency)}
                          name={seriesLabel(s.listing)}
                          note={notes.length ? notes.join(' · ') : undefined}
                        />
                      )
                    })}
                  </TooltipFrame>
                )
              }}
            />
            {target != null ? (
              <ReferenceLine
                y={target}
                stroke={chart.drop}
                strokeDasharray="4 4"
                label={{
                  value: `Target ${formatMoney(data.target_price, data.currency)}`,
                  position: 'insideTopRight',
                  fill: chart.inkSecondary,
                  fontSize: 11,
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
              />
            ) : null}
            {plotted.map((s) => (
              <Line
                key={s.listing.listing_id}
                dataKey={`l${s.listing.listing_id}`}
                type="stepAfter"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                dot={false}
                activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {plotted.length > 1 || foldedCount > 0 ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-2">
          {plotted.map((s) => (
            <span key={s.listing.listing_id} className="flex items-center gap-1.5 text-xs text-ink-2">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
              {seriesLabel(s.listing)}
            </span>
          ))}
          {foldedCount > 0 ? (
            <span className="flex items-center gap-1.5 text-xs text-ink-3">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: chart.othersGray }} />
              Others ({foldedCount}) — see listings below
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
