import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  RefObject,
} from 'react'
import { formatMoney } from '@/lib/money'
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

/** The plot box in SVG pixels plus the scales between it and (timestamp, price) space. */
export interface Plot {
  box: { l: number; r: number; t: number; b: number }
  x: (ts: number) => number
  y: (price: number) => number
  tsAt: (px: number) => number
}

const MARGIN = { l: 54, r: 14, t: 14, b: 30 } as const
/** Beam dead zone before the right edge — keeps the scan off the now-dots. */
const BEAM_INSET = 30
const TICK_FONT = { fontSize: 12, fontFamily: "'IBM Plex Mono', monospace" } as const
/** How long a finger must rest on the chart before it scans instead of scrolling the page. */
const LONG_PRESS_MS = 350
/** Movement that turns a pending long-press into a scroll. */
const PRESS_SLOP = 10

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

/**
 * Build the plot box and linear scales for a chart of the given size and
 * domain. Zero-width spans are widened (a minute, a dollar) so a single point
 * still plots.
 */
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

/**
 * Straight-segment path through the points, extended flat to endX when that
 * lies past the last point.
 */
export function polylineD(pts: Pt[], endX?: number): string {
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${f(p.x)} ${f(p.y)}`).join(' ')
  return endX != null && endX > pts[pts.length - 1].x ? `${d} H ${f(endX)}` : d
}

/** Evenly spaced x-axis labels, roughly one per 150px, formatted for the range. */
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

/**
 * The labeled step for a price span: 1-2-5 dollars, then 1-2.5-5 per decade,
 * always the smallest that leaves at most five majors. Worked out from the
 * span's magnitude rather than a fixed ladder, so a huge target (the column
 * allows $99,999,999.99) can't turn the ruler into tens of thousands of lines.
 */
function majorStepFor(span: number): number {
  const decade = Math.max(1, 10 ** Math.floor(Math.log10(span / 5)))
  const mantissas = decade === 1 ? [1, 2, 5, 10] : [1, 2.5, 5, 10]
  return (mantissas.find((m) => span / (m * decade) <= 5) ?? 10) * decade
}

/**
 * Ruler ticks for the y domain: minors every fifth of a major step, majors
 * labeled. Past $100k the labels go compact ($250k, $25M), in one unit for
 * the whole axis and with the step's precision: a full `$100000000` is wider
 * than the left margin and clips.
 */
export function priceTicks(yMin: number, yMax: number): { v: number; label: string | null }[] {
  const major = majorStepFor(yMax - yMin)
  const minor = major / 5
  const [unit, suffix] = yMax < 100_000 ? [1, ''] : yMax < 1_000_000 ? [1000, 'k'] : [1_000_000, 'M']
  const perUnit = major / unit
  const decimals = [0, 1, 2, 3].find((d) => Number.isInteger(+(perUnit * 10 ** d).toFixed(6))) ?? 3
  const ticks: { v: number; label: string | null }[] = []
  for (let k = Math.ceil(yMin / minor); k * minor <= yMax + 1e-9; k++) {
    const v = k * minor
    const amount = unit === 1 ? `${+v.toFixed(2)}` : (v / unit).toFixed(decimals)
    ticks.push({ v, label: k % 5 === 0 && v > yMin ? `$${amount}${suffix}` : null })
  }
  return ticks
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
  const ticks = priceTicks(yMin, yMax)
  const yTarget = target != null ? plot.y(target) : null

  return (
    <g>
      <rect x={l} y={t} width={r - l} height={b - t} fill={chart.well} stroke={chart.hairline} rx={4} />
      <line x1={l} y1={t} x2={l} y2={b} stroke={chart.hairlineStrong} />
      {ticks.map(({ v, label }) => (
        <g key={v}>
          {label != null ? <line x1={l} y1={plot.y(v)} x2={r} y2={plot.y(v)} stroke={chart.hairline} /> : null}
          <line x1={l - (label != null ? 8 : 4)} y1={plot.y(v)} x2={l} y2={plot.y(v)} stroke={chart.hairlineStrong} />
          {label != null ? (
            <text x={l - 12} y={plot.y(v) + 3} textAnchor="end" fill={chart.inkMuted} {...TICK_FONT}>
              {label}
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

/** One stretch of a trace; dashed while the listing was out of stock. */
export interface TraceSeg {
  d: string
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

/** Where the sweep beam sits: plot-space x/y and the timestamp under it. */
export interface SweepPos {
  x: number
  y: number
  ts: number
  /** placed by the arrow keys, so the chart's live region announces it */
  keyed: boolean
}

/**
 * The text alternative's price summary: `low $X, high $Y, now $Z, target $T`.
 * A null `now` reads as out of stock; a null target is left out.
 */
export function priceSummary(
  values: number[],
  now: number | null,
  target: number | null,
  currency: string,
): string {
  const money = (n: number) => formatMoney(n.toFixed(2), currency)
  const parts = [
    `low ${money(Math.min(...values))}`,
    `high ${money(Math.max(...values))}`,
    now != null ? `now ${money(now)}` : 'now out of stock',
  ]
  if (target != null) parts.push(`target ${money(target)}`)
  return parts.join(', ')
}

/**
 * The stop an arrow key moves the keyboard scan to, out of `count` stops.
 * From no stop yet, Left starts at the latest and Right at the earliest;
 * keys that aren't steps return null.
 */
export function stepStop(count: number, current: number | null, key: string): number | null {
  if (count === 0) return null
  const last = count - 1
  switch (key) {
    case 'ArrowLeft':
      return current == null ? last : Math.max(0, current - 1)
    case 'ArrowRight':
      return current == null ? 0 : Math.min(last, current + 1)
    case 'Home':
      return 0
    case 'End':
      return last
    default:
      return null
  }
}

/**
 * Scan state for a chart's SVG, spread onto it as `svgProps`. A mouse or pen
 * scans on hover. A finger scans only after a long-press: the SVG is
 * `touch-action: pan-y`, so a swipe that starts on the chart still scrolls
 * the page, and once the press is held a non-passive touchmove keeps the
 * drag on the chart. The arrow keys (plus Home/End) step through `stops`,
 * the check timestamps in ascending order; Escape or leaving the chart
 * clears the scan.
 */
export function useSweep(
  plot: Plot | null,
  stops: number[],
): {
  pos: SweepPos | null
  svgProps: {
    ref: (el: SVGSVGElement | null) => (() => void) | undefined
    tabIndex: number
    onPointerDown: (e: ReactPointerEvent<SVGSVGElement>) => void
    onPointerMove: (e: ReactPointerEvent<SVGSVGElement>) => void
    onPointerUp: (e: ReactPointerEvent<SVGSVGElement>) => void
    onPointerLeave: () => void
    onPointerCancel: () => void
    onContextMenu: (e: ReactMouseEvent<SVGSVGElement>) => void
    onKeyDown: (e: ReactKeyboardEvent<SVGSVGElement>) => void
    onBlur: () => void
  }
} {
  const [pos, setPos] = useState<SweepPos | null>(null)
  const press = useRef<{ x: number; y: number; timer: number | null; held: boolean } | null>(null)

  const endPress = () => {
    if (press.current?.timer != null) window.clearTimeout(press.current.timer)
    press.current = null
  }
  useEffect(() => endPress, [])

  const clear = () => {
    endPress()
    setPos(null)
  }

  const place = (x: number, y: number) => {
    if (!plot) return
    const { l, r, t, b } = plot.box
    if (x < l || x > r - BEAM_INSET || y < t || y > b) setPos(null)
    else setPos({ x, y, ts: plot.tsAt(x), keyed: false })
  }

  const local = (e: ReactPointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  // React registers touchmove as passive, so the scroll lock needs its own listener.
  const ref = useCallback((el: SVGSVGElement | null) => {
    if (!el) return undefined
    const onTouchMove = (e: TouchEvent) => {
      if (press.current?.held && e.cancelable) e.preventDefault()
    }
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    return () => el.removeEventListener('touchmove', onTouchMove)
  }, [])

  return {
    pos,
    svgProps: {
      ref,
      tabIndex: 0,
      onPointerDown: (e) => {
        if (e.pointerType !== 'touch') return
        endPress()
        const { x, y } = local(e)
        const p = { x, y, timer: null as number | null, held: false }
        p.timer = window.setTimeout(() => {
          p.timer = null
          p.held = true
          place(p.x, p.y)
        }, LONG_PRESS_MS)
        press.current = p
      },
      onPointerMove: (e) => {
        const { x, y } = local(e)
        if (e.pointerType === 'touch') {
          const p = press.current
          if (!p) return
          if (p.held) place(x, y)
          else if (Math.hypot(x - p.x, y - p.y) > PRESS_SLOP) endPress()
          return
        }
        place(x, y)
      },
      onPointerUp: (e) => {
        if (e.pointerType === 'touch') clear()
      },
      onPointerLeave: () => {
        if (!pos?.keyed) clear()
      },
      onPointerCancel: clear,
      // a held press would otherwise open the long-press callout over the scan
      onContextMenu: (e) => {
        if (press.current) e.preventDefault()
      },
      onKeyDown: (e) => {
        if (!plot) return
        if (e.key === 'Escape' && pos) {
          e.preventDefault()
          setPos(null)
          return
        }
        const current = pos?.keyed ? stops.indexOf(pos.ts) : -1
        const next = stepStop(stops.length, current >= 0 ? current : null, e.key)
        if (next == null) return
        e.preventDefault()
        const ts = stops[next]
        setPos({ x: plot.x(ts), y: plot.box.t, ts, keyed: true })
      },
      onBlur: () => {
        if (pos?.keyed) setPos(null)
      },
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
  // 250 = assumed tip width, 266 = that plus the 16px cursor offset
  const left = x + 16 + 250 > width ? Math.max(4, x - 266) : x + 16
  return (
    <div className="pointer-events-none absolute z-10" style={{ left, top: Math.max(4, y - 14) }}>
      {children}
    </div>
  )
}
