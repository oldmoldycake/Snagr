import { useId, useMemo } from 'react'
import type { PriceSummaryResponse } from '@/api/types'
import { chart } from '@/components/charts/chartTheme'
import { TooltipFrame, TooltipRow, tooltipTimeLabel } from '@/components/charts/ChartTooltip'
import {
  easedStepD,
  EmberTrace,
  FloatingTip,
  GlowDefs,
  makePlot,
  PlotFrame,
  polylineD,
  priceDomain,
  SweepBeam,
  timeTicks,
  useMeasuredWidth,
  useSweep,
} from '@/components/charts/pricePlot'
import { formatMoney } from '@/lib/money'
import { tickFormatterFor, type TimeRange } from '@/lib/time'

const HEIGHT = 256 // h-64

const BEST_LABEL = 'Best price'
const AVG_LABEL = 'Average across listings'

interface LinePoint {
  ts: number
  value: number
}

/** Latest value at-or-before ts, step semantics — matches the per-listing scan. */
function valueAt(pts: LinePoint[], ts: number): number | null {
  let result: number | null = null
  for (const p of pts) {
    if (p.ts > ts) break
    result = p.value
  }
  return result
}

export function AvgBestChart({ data, range }: { data: PriceSummaryResponse; range: TimeRange }) {
  const glowId = useId()
  const { ref, width } = useMeasuredWidth()

  const { avgPts, bestPts } = useMemo(() => {
    const avgPts: LinePoint[] = []
    const bestPts: LinePoint[] = []
    for (const p of data.points) {
      const ts = new Date(p.ts).getTime()
      if (p.avg != null) avgPts.push({ ts, value: Number(p.avg) })
      if (p.best != null) bestPts.push({ ts, value: Number(p.best) })
    }
    return { avgPts, bestPts }
  }, [data])

  const target = data.target_price != null ? Number(data.target_price) : null

  const geom = useMemo(() => {
    if (width === 0) return null
    const domain = priceDomain(
      [...avgPts, ...bestPts].map((p) => p.value),
      target,
    )
    if (!domain) return null
    const xMin = Math.min(...[...avgPts, ...bestPts].map((p) => p.ts))
    const xMax = Date.now()
    const plot = makePlot(width, HEIGHT, xMin, xMax, domain[0], domain[1])
    const nowX = plot.x(xMax)

    // avg: smoothed polyline, ember tip on the final segment
    const avgPx = avgPts.map((p) => ({ x: plot.x(p.ts), y: plot.y(p.value) }))
    const avg =
      avgPx.length > 0
        ? {
            segs: [{ d: polylineD(avgPx, nowX), dash: false }],
            tipD:
              avgPx.length > 1
                ? `M ${avgPx[avgPx.length - 2].x} ${avgPx[avgPx.length - 2].y} L ${avgPx[avgPx.length - 1].x} ${avgPx[avgPx.length - 1].y} H ${nowX}`
                : `M ${avgPx[0].x} ${avgPx[0].y} H ${nowX}`,
            now: { x: nowX, y: avgPx[avgPx.length - 1].y },
          }
        : null

    // best: eased steps like the per-listing traces, tip from the last change
    const bestPx = bestPts.map((p) => ({ x: plot.x(p.ts), y: plot.y(p.value) }))
    let best = null
    if (bestPx.length > 0) {
      const final = bestPts[bestPts.length - 1].value
      let runStart = bestPts.length - 1
      while (runStart > 0 && bestPts[runStart - 1].value === final) runStart--
      const y = plot.y(final)
      best = {
        segs: [{ d: easedStepD(bestPx, nowX), dash: false }],
        tipD: `M ${plot.x(bestPts[runStart].ts)} ${y} H ${nowX}`,
        now: { x: nowX, y },
      }
    }

    return { plot, domain, avg, best, xTicks: timeTicks(plot, xMin, xMax, range) }
  }, [width, avgPts, bestPts, target, range])

  const sweep = useSweep(geom?.plot ?? null)

  if (avgPts.length === 0 && bestPts.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-[13px] text-ink-3">
        Not enough data to summarize yet — run the agent to collect prices.
      </p>
    )
  }

  // Rows the beam strikes, sorted by price — best reads above avg.
  const candidates: { label: string; color: string; value: number | null }[] = sweep.pos
    ? [
        { label: BEST_LABEL, color: chart.ink, value: valueAt(bestPts, sweep.pos.ts) },
        { label: AVG_LABEL, color: chart.series[0], value: valueAt(avgPts, sweep.pos.ts) },
      ]
    : []
  const struck = candidates
    .filter((r): r is { label: string; color: string; value: number } => r.value != null)
    .sort((a, b) => a.value - b.value)

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
            {geom.avg ? (
              <EmberTrace
                segs={geom.avg.segs}
                tipD={geom.avg.tipD}
                color={chart.series[0]}
                now={geom.avg.now}
                cold={false}
                glowId={glowId}
              />
            ) : null}
            {geom.best ? (
              <EmberTrace
                segs={geom.best.segs}
                tipD={geom.best.tipD}
                color={chart.ink}
                now={geom.best.now}
                cold={false}
                glowId={glowId}
              />
            ) : null}
            {sweep.pos && struck.length > 0 ? (
              <SweepBeam
                plot={geom.plot}
                x={sweep.pos.x}
                dateLabel={tickFormatterFor(range)(sweep.pos.ts).toLowerCase()}
                points={struck.map((r) => ({ y: geom.plot.y(r.value), color: r.color }))}
                glowId={glowId}
              />
            ) : null}
          </svg>
        ) : null}
        {sweep.pos && struck.length > 0 ? (
          <FloatingTip x={sweep.pos.x} y={sweep.pos.y} width={width}>
            <TooltipFrame label={tooltipTimeLabel(sweep.pos.ts)}>
              {struck.map((r) => (
                <TooltipRow
                  key={r.label}
                  color={r.color}
                  value={formatMoney(r.value.toFixed(2), data.currency)}
                  name={r.label}
                  under={target != null && r.value <= target}
                />
              ))}
            </TooltipFrame>
          </FloatingTip>
        ) : null}
      </div>
      <div className="flex items-center gap-4 px-4 pt-2">
        <span className="flex items-center gap-1.5 text-xs text-ink-2">
          <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: chart.ink }} />
          {BEST_LABEL}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-2">
          <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: chart.series[0] }} />
          {AVG_LABEL}
        </span>
      </div>
    </div>
  )
}
