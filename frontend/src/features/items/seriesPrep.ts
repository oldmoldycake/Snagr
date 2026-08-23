import type { ListingSeries, PriceHistoryResponse } from '@/api/types'
import { chart, seriesColor } from '@/components/charts/chartTheme'

export const MAX_SERIES = 6

export interface PreparedSeries {
  listing: ListingSeries
  color: string
  points: { ts: number; price: number; in_stock: boolean }[]
}

/**
 * Shared slot/color/fold logic for the per-listing chart and the listings
 * board. Both must agree exactly — a board row may only claim a series color
 * the chart actually drew, so folded listings get the "others" gray in both.
 */
export function prepareSeries(data: PriceHistoryResponse): {
  plotted: PreparedSeries[]
  foldedCount: number
  colorOf: (listingId: number) => string
} {
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

  const plottedColor = new Map(plotted.map((s) => [s.listing.listing_id, s.color]))
  return {
    plotted,
    foldedCount,
    colorOf: (listingId) => plottedColor.get(listingId) ?? chart.othersGray,
  }
}
