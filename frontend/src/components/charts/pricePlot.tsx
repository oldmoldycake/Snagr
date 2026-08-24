import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, RefObject } from 'react'
import { tickFormatterFor, type TimeRange } from '@/lib/time'
import { chart, mixToWhite } from './chartTheme'

/**
 * Shared primitives for the hand-rolled price charts (PriceHistoryChart,
 * AvgBestChart): the plot box + scales, the well/ruler/target-zone chrome,
 * eased-step path geometry, the ember-tip glow, and the sweep-beam scan.
 * Recharts remains only in CategoryChangeChart.
 */

export interface Pt {
  x: number
  y: number
}

export interface Plot {
  box: { l: number; r: number; t: number; b: number }
  x: (ts: number) => number
  y: (price: number) => number
  tsAt: (px: number) => number
}

const MARGIN = { l: 54, r: 14, t: 14, b: 30 } as const
/** Beam dead zone before the right edge — keeps the scan off the now-dots. */
const BEAM_INSET = 30
const TICK_FONT = { fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" } as const

/** Measured width of the chart's container — the ResponsiveContainer stand-in. */
export function useMeasuredWidth(): { ref: RefObject<HTMLDivElement | null>; width: number } {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  return { ref, width }
}

/** Y domain including the target: pad ×0.97/×1.02, snap to $10. */
export function priceDomain(values: number[], target: number | null): [number, number] | null {
  const all = target != null ? [...values, target] : values
  if (all.length === 0) return null
  const min = Math.min(...all)
  const max = Math.max(...all)
  return [Math.floor((min * 0.97) / 10) * 10, Math.ceil((max * 1.02) / 10) * 10]
}

export function makePlot(
  width: number,
  height: number,
  xMin: number,
  xMax: number,
  yMin: number,
  yMax: number,
): Plot {
  const box = { l: MARGIN.l, r: width - MARGIN.r, t: MARGIN.t, b: height - MARGIN.b }
  const xSpan = Math.max(xMax - xMin, 60_000)
  const ySpan = Math.max(yMax - yMin, 1)
  return {
    box,
    x: (ts) => box.l + ((ts - xMin) / xSpan) * (box.r - box.l),
    y: (price) => box.b - ((price - yMin) / ySpan) * (box.b - box.t),
    tsAt: (px) => xMin + Math.max(0, Math.min(1, (px - box.l) / (box.r - box.l))) * xSpan,
  }
}

const f = (n: number) => +n.toFixed(2)

/**
 * Step-after path with arc-eased corners, r = min(2, |Δy|/2, Δx/2). With endX
 * the final run extends there (carry-forward to "now"); without it the path
 * stops exactly at the last point so a following stretch can continue it.
 */
export function easedStepD(pts: Pt[], endX?: number): string {
  let d = `M ${f(pts[0].x)} ${f(pts[0].y)}`
  let px = pts[0].x
  let py = pts[0].y
  for (let i = 1; i < pts.length; i++) {
    const { x: xi, y: yi } = pts[i]
    const dy = yi - py
    if (Math.abs(dy) < 0.5) {
      px = xi
      continue
    }
    const r = Math.min(2, Math.abs(dy) / 2, Math.max(0, (xi - px) / 2))
    if (r < 0.5) {
      d += ` H ${f(xi)} V ${f(yi)}`
    } else {
      const sgn = dy > 0 ? 1 : -1
      d += ` H ${f(xi - r)} A ${f(r)} ${f(r)} 0 0 ${sgn > 0 ? 1 : 0} ${f(xi)} ${f(py + sgn * r)}`
      if (i === pts.length - 1 && endX == null) {
        d += ` V ${f(yi)}`
      } else {
        d += ` V ${f(yi - sgn * r)} A ${f(r)} ${f(r)} 0 0 ${sgn > 0 ? 0 : 1} ${f(xi + r)} ${f(yi)}`
      }
    }
    px = xi
    py = yi
  }
  return `${d} H ${f(endX ?? pts[pts.length - 1].x)}`
}

/** Plain polyline (the "smoothed" avg trace), optionally carried flat to endX. */
export function polylineD(pts: Pt[], endX?: number): string {
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${f(p.x)} ${f(p.y)}`).join(' ')
  return endX != null && endX > pts[pts.length - 1].x ? `${d} H ${f(endX)}` : d
}

/** Evenly spaced x-axis ticks, ~150px apart, inset half a step from the edges. */
export function timeTicks(
  plot: Plot,
  xMin: number,
  xMax: number,
  range: TimeRange,
): { x: number; label: string }[] {
  const n = Math.max(2, Math.round((plot.box.r - plot.box.l) / 150))
  const fmt = tickFormatterFor(range)
  return Array.from({ length: n }, (_, i) => {
    const ts = xMin + ((i + 0.5) / n) * (xMax - xMin)
    return { x: plot.x(ts), label: fmt(ts) }
  })
}

/** Smallest "nice" major step giving at most 5 majors over the span. */
function majorStepFor(span: number): number {
  const steps = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
  return steps.find((s) => span / s <= 5) ?? 10_000
}

/**
 * The static chrome: well ground, graduated ruler (minors every fifth of a
 * major, labeled majors with a faint gridline), x axis, and the target zone.
 * While the beam is up, tick labels near it yield to the beam's date.
 */
export function PlotFrame({
  plot,
  yMin,
  yMax,
  xTicks,
  target,
  targetLabel,
  beamX,
}: {
  plot: Plot
  yMin: number
  yMax: number
  xTicks: { x: number; label: string }[]
  target: number | null
  targetLabel: string
  beamX: number | null
}) {
  const { l, r, t, b } = plot.box
  const minor = majorStepFor(yMax - yMin) / 5
  const ticks: { v: number; major: boolean }[] = []
  for (let k = Math.ceil(yMin / minor); k * minor <= yMax + 1e-9; k++) {
    ticks.push({ v: k * minor, major: k % 5 === 0 && k * minor > yMin })
  }
  const yTarget = target != null ? plot.y(target) : null

  return (
    <g>
      <rect x={l} y={t} width={r - l} height={b - t} fill={chart.well} stroke={chart.hairline} rx={4} />
      <line x1={l} y1={t} x2={l} y2={b} stroke={chart.hairlineStrong} />
      {ticks.map(({ v, major }) => (
        <g key={v}>
          {major ? <line x1={l} y1={plot.y(v)} x2={r} y2={plot.y(v)} stroke={chart.hairline} /> : null}
          <line x1={l - (major ? 8 : 4)} y1={plot.y(v)} x2={l} y2={plot.y(v)} stroke={chart.hairlineStrong} />
          {major ? (
            <text x={l - 12} y={plot.y(v) + 3} textAnchor="end" fill={chart.inkMuted} {...TICK_FONT}>
              {`$${+v.toFixed(2)}`}
            </text>
          ) : null}
        </g>
      ))}
      {yTarget != null ? (
        <g>
          <rect x={l} y={yTarget} width={r - l} height={b - yTarget} fill={chart.drop} opacity={0.08} />
          <line x1={l} y1={yTarget} x2={r} y2={yTarget} stroke={chart.drop} opacity={0.5} strokeDasharray="4 4" />
          <text
            x={r - 8}
            y={yTarget - 6}
            textAnchor="end"
            fill={chart.drop}
            letterSpacing="0.08em"
            {...TICK_FONT}
          >
            {targetLabel}
          </text>
        </g>
      ) : null}
      <line x1={l} y1={b} x2={r} y2={b} stroke={chart.hairlineStrong} />
      {xTicks.map(({ x, label }) =>
        beamX != null && Math.abs(x - beamX) < 40 ? null : (
          <text key={x} x={x} y={b + 18} textAnchor="middle" fill={chart.inkMuted} {...TICK_FONT}>
            {label}
          </text>
        ),
      )}
    </g>
  )
}

/** Gaussian-blur filters for the ember tip / struck points (σ2.2) and the now-dot (σ2.6). */
export function GlowDefs({ id }: { id: string }) {
  return (
    <defs>
      <filter id={`${id}-tip`} x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation={2.2} />
      </filter>
      <filter id={`${id}-dot`} x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation={2.6} />
      </filter>
    </defs>
  )
}

export interface TraceSeg {
  d: string
  /** out-of-stock stretch: dashed 2 4 at 55%, never glowing */
  dash: boolean
}

/**
 * One trace with the ember tip: solid/dashed stretches, a halo over the final
 * run, and the glowing now-dot. A cold trace (latest check out-of-stock) keeps
 * only a dimmed core dot — the ember has gone out.
 */
export function EmberTrace({
  segs,
  tipD,
  color,
  now,
  cold,
  glowId,
}: {
  segs: TraceSeg[]
  tipD: string | null
  color: string
  now: Pt
  cold: boolean
  glowId: string
}) {
  return (
    <g>
      {segs.map((seg, i) => (
        <path
          key={i}
          d={seg.d}
          fill="none"
          stroke={color}
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeDasharray={seg.dash ? '2 4' : undefined}
          opacity={seg.dash ? 0.55 : 1}
        />
      ))}
      {!cold && tipD ? (
        <path
          d={tipD}
          fill="none"
          stroke={mixToWhite(color, 0.1)}
          strokeWidth={3}
          strokeLinecap="round"
          opacity={0.7}
          filter={`url(#${glowId}-tip)`}
        />
      ) : null}
      {!cold ? (
        <circle cx={now.x} cy={now.y} r={5.5} fill={color} opacity={0.65} filter={`url(#${glowId}-dot)`} />
      ) : null}
      <circle
        cx={now.x}
        cy={now.y}
        r={4}
        fill={mixToWhite(color, 0.3)}
        stroke={chart.well}
        strokeWidth={2}
        opacity={cold ? 0.55 : 1}
      />
    </g>
  )
}

export interface SweepPos {
  x: number
  y: number
  ts: number
}

/** Cursor scan state — pointer events, so touch-drag scans too. */
export function useSweep(plot: Plot | null): {
  pos: SweepPos | null
  handlers: {
    onPointerMove: (e: ReactPointerEvent<SVGSVGElement>) => void
    onPointerLeave: () => void
    onPointerCancel: () => void
  }
} {
  const [pos, setPos] = useState<SweepPos | null>(null)
  const clear = () => setPos(null)
  return {
    pos,
    handlers: {
      onPointerMove: (e) => {
        if (!plot) return
        const rect = e.currentTarget.getBoundingClientRect()
        const x = e.clientX - rect.left
        const y = e.clientY - rect.top
        const { l, r, t, b } = plot.box
        if (x < l || x > r - BEAM_INSET || y < t || y > b) clear()
        else setPos({ x, y, ts: plot.tsAt(x) })
      },
      onPointerLeave: clear,
      onPointerCancel: clear,
    },
  }
}

/** The lume scanline: beam, its date on the axis, and a struck point per trace. */
export function SweepBeam({
  plot,
  x,
  dateLabel,
  points,
  glowId,
}: {
  plot: Plot
  x: number
  dateLabel: string
  points: { y: number; color: string }[]
  glowId: string
}) {
  const { t, b } = plot.box
  return (
    <g pointerEvents="none">
      <line x1={x} x2={x} y1={t} y2={b} stroke={chart.lume} opacity={0.5} />
      <text x={x} y={b + 18} textAnchor="middle" fill={chart.lume} {...TICK_FONT}>
        {dateLabel}
      </text>
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={x} cy={p.y} r={4.5} fill={p.color} opacity={0.6} filter={`url(#${glowId}-tip)`} />
          <circle cx={x} cy={p.y} r={2.5} fill={mixToWhite(p.color, 0.35)} stroke={chart.well} strokeWidth={1} />
        </g>
      ))}
    </g>
  )
}

/** Floating tooltip container: offset right of the cursor, flipped near the edge. */
export function FloatingTip({
  x,
  y,
  width,
  children,
}: {
  x: number
  y: number
  width: number
  children: ReactNode
}) {
  const left = x + 16 + 250 > width ? Math.max(4, x - 266) : x + 16
  return (
    <div className="pointer-events-none absolute z-10" style={{ left, top: Math.max(4, y - 14) }}>
      {children}
    </div>
  )
}
