import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CategoryItemChange } from '@/api/types'
import { axisTickStyle, chart } from '@/components/charts/chartTheme'
import { TooltipFrame, TooltipRow } from '@/components/charts/ChartTooltip'
import { formatMoney } from '@/lib/money'

const MAX_BARS = 15

/**
 * Diverging horizontal bars: % change of best price over the range, centered
 * at 0. Drops (good) green, rises red — polarity semantics, not series colors.
 */
export function CategoryChangeChart({ items }: { items: CategoryItemChange[] }) {
  const data = items
    .filter((i) => i.pct_change != null)
    .map((i) => ({ ...i, pct: Number(i.pct_change) }))
    .sort((a, b) => a.pct - b.pct)
  const shown = data.slice(0, MAX_BARS)

  if (shown.length === 0) {
    return <p className="px-4 py-6 text-[13px] text-ink-3">Not enough price history in this range yet.</p>
  }

  const height = Math.max(120, shown.length * 34 + 30)

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={shown} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 8 }}>
          <XAxis
            type="number"
            tick={axisTickStyle}
            tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${v}%`}
            axisLine={false}
            tickLine={false}
            domain={['auto', 'auto']}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={170}
            tick={{ fill: chart.inkSecondary, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <ReferenceLine x={0} stroke={chart.grid} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.03)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const row = payload[0].payload as (typeof shown)[number]
              return (
                <TooltipFrame label={row.name}>
                  <TooltipRow
                    color={row.pct <= 0 ? chart.drop : chart.rise}
                    value={`${row.pct > 0 ? '+' : ''}${row.pct.toFixed(1)}%`}
                    name={`${formatMoney(row.old_best)} → ${formatMoney(row.new_best)}`}
                  />
                </TooltipFrame>
              )
            }}
          />
          <Bar dataKey="pct" barSize={18} radius={[0, 3, 3, 0]}>
            {shown.map((row) => (
              <Cell key={row.item_id} fill={row.pct <= 0 ? chart.drop : chart.rise} fillOpacity={0.85} />
            ))}
            <LabelList
              dataKey="pct"
              position="right"
              formatter={(v: unknown) => `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`}
              style={{ fill: chart.inkSecondary, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {data.length > MAX_BARS ? (
        <p className="px-4 pb-2 text-xs text-ink-3">
          Showing the {MAX_BARS} biggest movers — the table below has every item.
        </p>
      ) : null}
    </div>
  )
}
