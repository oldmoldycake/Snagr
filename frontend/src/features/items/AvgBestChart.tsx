import { useMemo } from 'react'
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PriceSummaryResponse } from '@/api/types'
import { axisTickStyle, chart } from '@/components/charts/chartTheme'
import { TooltipFrame, TooltipRow, tooltipTimeLabel } from '@/components/charts/ChartTooltip'
import { formatMoney } from '@/lib/money'
import { tickFormatterFor, type TimeRange } from '@/lib/time'

const BEST_COLOR = '#c9ced4'
const AVG_COLOR = chart.series[0]

export function AvgBestChart({ data, range }: { data: PriceSummaryResponse; range: TimeRange }) {
  const { rows, yDomain } = useMemo(() => {
    const rows = data.points.map((p) => ({
      ts: new Date(p.ts).getTime(),
      avg: p.avg != null ? Number(p.avg) : null,
      best: p.best != null ? Number(p.best) : null,
    }))
    const values = rows.flatMap((r) => [r.avg, r.best]).filter((v): v is number => v != null)
    const target = data.target_price != null ? Number(data.target_price) : null
    if (values.length === 0) return { rows, yDomain: [0, 100] as [number, number] }
    const min = Math.min(...values, ...(target != null ? [target] : []))
    const max = Math.max(...values, ...(target != null ? [target] : []))
    return {
      rows,
      yDomain: [Math.floor((min * 0.97) / 10) * 10, Math.ceil((max * 1.02) / 10) * 10] as [number, number],
    }
  }, [data])

  const hasData = rows.some((r) => r.avg != null || r.best != null)
  if (!hasData) {
    return (
      <p className="px-4 py-10 text-center text-[13px] text-ink-3">
        Not enough data to summarize yet — run the agent to collect prices.
      </p>
    )
  }

  const target = data.target_price != null ? Number(data.target_price) : null

  return (
    <div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
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
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const row = payload[0].payload as (typeof rows)[number]
                return (
                  <TooltipFrame label={tooltipTimeLabel(Number(label))}>
                    {row.best != null ? (
                      <TooltipRow color={BEST_COLOR} value={formatMoney(row.best.toFixed(2), data.currency)} name="Best price" />
                    ) : null}
                    {row.avg != null ? (
                      <TooltipRow color={AVG_COLOR} value={formatMoney(row.avg.toFixed(2), data.currency)} name="Average across listings" />
                    ) : null}
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
            <Area
              dataKey="avg"
              type="monotone"
              stroke={AVG_COLOR}
              strokeWidth={2}
              fill={AVG_COLOR}
              fillOpacity={0.1}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              dataKey="best"
              type="monotone"
              stroke={BEST_COLOR}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 px-4 pt-2">
        <span className="flex items-center gap-1.5 text-xs text-ink-2">
          <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: BEST_COLOR }} />
          Best price
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-2">
          <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: AVG_COLOR }} />
          Average across listings
        </span>
      </div>
    </div>
  )
}
