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
  priceSummary,
  SweepBeam,
  timeTicks,
  useMeasuredWidth,
  useSweep,
  type Plot,
  type TraceSeg,
} from '@/components/charts/pricePlot'
import { formatMoney } from '@/lib/money'
import { tickFormatterFor, type TimeRange } from '@/lib/time'
import { sharedTitlePrefix } from './listingTitles'
import { prepareSeries, type PreparedSeries } from './seriesPrep'

const HEIGHT = 256
const END_LABEL_GAP = 13

/**
 * Legend labels: strip the longest shared title prefix (whole words) among the
 * plotted listings so six near-identical titles read by their differences,
 * then append the site. Falls back to the site name alone.
 */
function seriesLabels(plotted: PreparedSeries[]): Map<number, string> {
  const prefix = sharedTitlePrefix(plotted.map((s) => s.listing.title))
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

/**
 * Each line's legend number, in the plot's right margin beside its end dot —
 * lines told apart by hue alone fail anyone who can't tell the hues apart.
 * Outside the well, so the target label never covers one; pushed apart
 * top-down so lines ending at near-equal prices stay legible.
 */
function EndLabels({ traces, plot, numbers }: { traces: Trace[]; plot: Plot; numbers: Map<number, number> }) {
  const placed = [...traces].sort((a, b) => a.now.y - b.now.y)
  const ys: number[] = []
  for (const tr of placed) {
    const prev = ys.at(-1)
    ys.push(Math.max(tr.now.y, plot.box.t + 8, prev != null ? prev + END_LABEL_GAP : -Infinity))
  }
  // the push can run off the bottom; pull the stack back up from there
  for (let i = ys.length - 1; i >= 0; i--) {
    const below = ys[i + 1]
    ys[i] = Math.min(ys[i], plot.box.b - 6, below != null ? below - END_LABEL_GAP : Infinity)
  }
  return (
    <g aria-hidden>
      {placed.map((tr, i) => (
        <text
          key={tr.series.listing.listing_id}
          x={tr.now.x + 6}
          y={ys[i] + 4}
          fill={chart.inkSecondary}
          fontSize={11}
          fontFamily="'IBM Plex Mono', monospace"
        >
          {numbers.get(tr.series.listing.listing_id)}
        </text>
      ))}
    </g>
  )
}

/** Per-listing price traces for one item over the range, with the ember tip and sweep-beam scan. */
export function PriceHistoryChart({ data, range }: { data: PriceHistoryResponse; range: TimeRange }) {
  const glowId = useId()
  const { ref, width } = useMeasuredWidth()

  const { plotted, foldedCount } = useMemo(() => prepareSeries(data), [data])
  const labels = useMemo(() => seriesLabels(plotted), [plotted])
  // one line needs no key; with several, each is numbered on the plot and in the legend
  const numbers = useMemo(
    () => new Map(plotted.length > 1 ? plotted.map((s, i) => [s.listing.listing_id, i + 1]) : []),
    [plotted],
  )
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

  const stops = useMemo(
    () => [...new Set(plotted.flatMap((s) => s.points.map((p) => p.ts)))].sort((a, b) => a - b),
    [plotted],
  )
  const sweep = useSweep(geom?.plot ?? null, stops)

  if (plotted.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-[14px] text-ink-3">
        No price history yet. It fills in as Snagr checks this item's listings.
      </p>
    )
  }

  const struck =
    geom && sweep.pos
      ? plotted
          .map((s) => ({ s, at: priceAt(s, sweep.pos!.ts) }))
          .filter((r): r is { s: PreparedSeries; at: NonNullable<ReturnType<typeof priceAt>> } => r.at != null)
          .sort((a, b) => a.at.price - b.at.price)
      : []

  const inStockNow = plotted.map((s) => s.points[s.points.length - 1]).filter((p) => p.in_stock)
  const summary = `Price history of ${plotted.length} ${plotted.length === 1 ? 'listing' : 'listings'}: ${priceSummary(
    plotted.flatMap((s) => s.points.map((p) => p.price)),
    inStockNow.length > 0 ? Math.min(...inStockNow.map((p) => p.price)) : null,
    target,
    data.currency,
  )}. Arrow keys step through the checks.`

  return (
    <div>
      <div ref={ref} className="relative h-64">
        {geom ? (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={summary}
            className="touch-pan-y select-none focus-visible:-outline-offset-2"
            {...sweep.svgProps}
          >
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
            {numbers.size > 0 ? <EndLabels traces={geom.traces} plot={geom.plot} numbers={numbers} /> : null}
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
      <p aria-live="polite" className="sr-only">
        {sweep.pos?.keyed
          ? `${tooltipTimeLabel(sweep.pos.ts)}: ${struck
              .map(
                ({ s, at }) =>
                  `${labels.get(s.listing.listing_id) ?? s.listing.site_name} ${formatMoney(at.price.toFixed(2), data.currency)}${at.in_stock ? '' : ', out of stock'}`,
              )
              .join('; ')}`
          : ''}
      </p>

      {plotted.length > 1 || foldedCount > 0 ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-2">
          {plotted.map((s) => (
            <span key={s.listing.listing_id} className="flex items-center gap-1.5 text-xs text-ink-2">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
              {numbers.has(s.listing.listing_id) ? (
                <span className="font-mono text-ink-3">{numbers.get(s.listing.listing_id)}</span>
              ) : null}
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
