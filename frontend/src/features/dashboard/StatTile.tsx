import type { StatTile as StatTileData } from '@/api/types'
import { Card } from '@/components/ui/card'
import { chart } from '@/components/charts/chartTheme'
import { cn } from '@/lib/cn'

/**
 * Stat tile: label → value → delta vs prior period → 12-point sparkline.
 * Delta color depends on the metric's goodness axis; "neutral" stays ink.
 */
export function StatTile({
  label,
  data,
  polarity = 'growth',
  glyphWhenPositive,
}: {
  label: string
  data: StatTileData | undefined
  polarity?: 'growth' | 'neutral'
  glyphWhenPositive?: string
}) {
  const delta = data?.delta ?? 0
  const deltaColor =
    polarity === 'neutral' || delta === 0
      ? 'text-ink-3'
      : delta > 0
        ? 'text-drop'
        : 'text-rise'

  return (
    <Card className="px-4 py-3">
      <p className="text-[11px] font-medium tracking-wide text-ink-3 uppercase">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div>
          <p className="font-display text-2xl font-semibold text-ink">{data?.value ?? '—'}</p>
          <p className={cn('mt-0.5 font-mono text-xs tnum', deltaColor)}>
            {data == null ? ' ' : (
              <>
                <span aria-hidden>{delta > 0 ? '▲' : delta < 0 ? '▼' : '—'}</span>{' '}
                {Math.abs(delta)}
                {delta > 0 && glyphWhenPositive ? ` ${glyphWhenPositive}` : ''} vs prior
              </>
            )}
          </p>
        </div>
        {data && data.spark.length > 1 ? <TileSpark values={data.spark} /> : null}
      </div>
    </Card>
  )
}

function TileSpark({ values }: { values: number[] }) {
  const width = 72
  const height = 26
  const pad = 2
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2)
    const y = height - pad - ((v - min) / span) * (height - pad * 2)
    return [x, y] as const
  })
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
      <circle cx={endX} cy={endY} r={2} fill={chart.inkSecondary} />
    </svg>
  )
}
