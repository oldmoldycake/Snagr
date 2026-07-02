import { chart } from './chartTheme'

/**
 * Row sparkline: 96×28 plain SVG, de-emphasis gray, 4px end dot colored by
 * direction of (last − first). Color is never the only channel — the adjacent
 * Δ column carries the signed number + glyph.
 */
export function Sparkline({
  data,
  width = 96,
  height = 28,
}: {
  data: (number | string | null)[]
  width?: number
  height?: number
}) {
  const values = data.map((v) => (v == null ? null : Number(v)))
  const present = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (present.length < 2) {
    return <span className="inline-block text-xs text-ink-3" style={{ width }}>—</span>
  }

  const min = Math.min(...present)
  const max = Math.max(...present)
  const span = max - min || 1
  const pad = 3

  const points: [number, number][] = []
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) return
    const x = pad + (i / (values.length - 1)) * (width - pad * 2)
    const y = height - pad - ((v - min) / span) * (height - pad * 2)
    points.push([x, y])
  })

  const first = present[0]
  const last = present[present.length - 1]
  const endColor = last < first ? chart.drop : last > first ? chart.rise : chart.inkMuted
  const [endX, endY] = points[points.length - 1]

  return (
    <svg width={width} height={height} aria-hidden className="shrink-0">
      <polyline
        points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}
        fill="none"
        stroke={chart.sparkDim}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={endX} cy={endY} r={2} fill={endColor} />
    </svg>
  )
}
