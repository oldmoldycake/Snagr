import { useId, useMemo } from 'react'
import type { PriceHistoryResponse } from '@/api/types'
import { chart } from '@/components/charts/chartTheme'
import { TooltipFrame, TooltipRow, tooltipTimeLabel } from '@/components/charts/ChartTooltip'
import {
  easedStepD,
  EmberTrace,
  FloatingTip,
  GlowDefs,
  makePlot,
  PlotFrame,
  priceDomain,
  SweepBeam,
  timeTicks,
  useMeasuredWidth,
  useSweep,
  type Plot,
  type TraceSeg,
} from '@/components/charts/pricePlot'
import { formatMoney } from '@/lib/money'
import { tickFormatterFor, type TimeRange } from '@/lib/time'
import { prepareSeries, type PreparedSeries } from './seriesPrep'

const HEIGHT = 256 // h-64

/**
 * Legend labels: strip the longest shared title prefix (whole words) among the
 * plotted listings so six near-identical titles read by their differences,
 * then append the site. Falls back to the site name alone.
 */
function seriesLabels(plotted: PreparedSeries[]): Map<number, string> {
  const titles = plotted.map((s) => s.listing.title).filter((t): t is string => t != null)
  let prefix = ''
  if (titles.length >= 2) {
    prefix = titles[0]
    for (const t of titles) while (!t.startsWith(prefix)) prefix = prefix.slice(0, -1)
    // a cut inside a word retreats to the word boundary
    if (titles.some((t) => t.length > prefix.length && t[prefix.length] !== ' ')) {
      prefix = prefix.slice(0, prefix.lastIndexOf(' ') + 1)
    }
  }
  return new Map(
    plotted.map((s) => {
      const raw = s.listing.title?.slice(prefix.length).trim() ?? ''
      // truncate the fragment, not the label — the site must survive
      const fragment = raw.length > 26 ? `${raw.slice(0, 25).trimEnd()}…` : raw
      const label = fragment ? `${fragment} · ${s.listing.site_name}` : s.listing.site_name
      return [s.listing.listing_id, label]
    }),
  )
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

interface Trace {
  series: PreparedSeries
  segs: TraceSeg[]
  tipD: string | null
  now: { x: number; y: number }
  cold: boolean
}

/**
 * Solid/dashed stretches (a check's stock status styles the stretch it opens)
 * plus the ember tip's final run — the flat stretch at the final price, from
 * the last price change to "now". A trace whose latest check is out-of-stock
 * is cold: dashed to the edge, no glow.
 */
function buildTrace(series: PreparedSeries, plot: Plot, nowTs: number): Trace {
  const pts = series.points
  const px = pts.map((p) => ({ x: plot.x(p.ts), y: plot.y(p.price) }))
  const last = pts[pts.length - 1]
  const nowX = plot.x(nowTs)

  const segs: TraceSeg[] = []
  let start = 0
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].in_stock === pts[start].in_stock) continue
    segs.push({ d: easedStepD(px.slice(start, i + 1)), dash: !pts[start].in_stock })
    start = i
  }
  segs.push({ d: easedStepD(px.slice(start), nowX), dash: !pts[start].in_stock })

  let runStart = pts.length - 1
  while (runStart > 0 && pts[runStart - 1].price === last.price && pts[runStart - 1].in_stock) runStart--

  const cold = !last.in_stock
  const y = plot.y(last.price)
  return {
    series,
    segs,
    tipD: cold ? null : `M ${plot.x(pts[runStart].ts)} ${y} H ${nowX}`,
    now: { x: nowX, y },
    cold,
  }
}

export function PriceHistoryChart({ data, range }: { data: PriceHistoryResponse; range: TimeRange }) {
  const glowId = useId()
  const { ref, width } = useMeasuredWidth()

  const { plotted, foldedCount } = useMemo(() => prepareSeries(data), [data])
  const labels = useMemo(() => seriesLabels(plotted), [plotted])
  const target = data.target_price != null ? Number(data.target_price) : null

  const geom = useMemo(() => {
    if (width === 0 || plotted.length === 0) return null
    const domain = priceDomain(
      plotted.flatMap((s) => s.points.map((p) => p.price)),
      target,
    )
    if (!domain) return null
    const xMin = Math.min(...plotted.map((s) => s.points[0].ts))
    const xMax = Date.now()
    const plot = makePlot(width, HEIGHT, xMin, xMax, domain[0], domain[1])
    return {
      plot,
      domain,
      traces: plotted.map((s) => buildTrace(s, plot, xMax)),
      xTicks: timeTicks(plot, xMin, xMax, range),
    }
  }, [width, plotted, target, range])

  const sweep = useSweep(geom?.plot ?? null)

  if (plotted.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-[13px] text-ink-3">
        No price history yet — run the agent to check this item's listings.
      </p>
    )
  }

  // Rows the beam strikes, sorted by price — the cheapest reads first.
  const struck =
    geom && sweep.pos
      ? plotted
          .map((s) => ({ s, at: priceAt(s, sweep.pos!.ts) }))
          .filter((r): r is { s: PreparedSeries; at: NonNullable<ReturnType<typeof priceAt>> } => r.at != null)
          .sort((a, b) => a.at.price - b.at.price)
      : []

  return (
    <div>
      <div ref={ref} className="relative h-64">
        {geom ? (
          <svg width={width} height={HEIGHT} className="touch-none" {...sweep.handlers}>
            <GlowDefs id={glowId} />
            <PlotFrame
              plot={geom.plot}
              yMin={geom.domain[0]}
              yMax={geom.domain[1]}
              xTicks={geom.xTicks}
              target={target}
              targetLabel={`⌖ TARGET ${formatMoney(data.target_price, data.currency)}`}
              beamX={struck.length > 0 ? sweep.pos!.x : null}
            />
            {geom.traces.map((tr) => (
              <EmberTrace
                key={tr.series.listing.listing_id}
                segs={tr.segs}
                tipD={tr.tipD}
                color={tr.series.color}
                now={tr.now}
                cold={tr.cold}
                glowId={glowId}
              />
            ))}
            {sweep.pos && struck.length > 0 ? (
              <SweepBeam
                plot={geom.plot}
                x={sweep.pos.x}
                dateLabel={tickFormatterFor(range)(sweep.pos.ts).toLowerCase()}
                points={struck.map((r) => ({ y: geom.plot.y(r.at.price), color: r.s.color }))}
                glowId={glowId}
              />
            ) : null}
          </svg>
        ) : null}
        {sweep.pos && struck.length > 0 ? (
          <FloatingTip x={sweep.pos.x} y={sweep.pos.y} width={width}>
            <TooltipFrame label={tooltipTimeLabel(sweep.pos.ts)}>
              {struck.map(({ s, at }) => (
                <TooltipRow
                  key={s.listing.listing_id}
                  color={s.color}
                  value={formatMoney(at.price.toFixed(2), data.currency)}
                  name={labels.get(s.listing.listing_id) ?? s.listing.site_name}
                  note={at.in_stock ? undefined : '○ out of stock'}
                  under={target != null && at.price <= target}
                />
              ))}
            </TooltipFrame>
          </FloatingTip>
        ) : null}
      </div>

      {plotted.length > 1 || foldedCount > 0 ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-2">
          {plotted.map((s) => (
            <span key={s.listing.listing_id} className="flex items-center gap-1.5 text-xs text-ink-2">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
              {labels.get(s.listing.listing_id)}
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
