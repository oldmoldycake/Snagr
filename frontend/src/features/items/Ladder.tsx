import { useMeasuredWidth } from '@/components/charts/pricePlot'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { RANGE_LABELS, type TimeRange } from '@/lib/time'
import { ladderLabelJoins } from './ladderLabels'

/**
 * The range ladder: a graduated rail from the range high down to the target,
 * with a glowing marker at the current best price. Uses the item's spark
 * series (bucketed best prices for the range) — no extra fetch.
 */
export function Ladder({
  spark,
  best,
  target,
  currency,
  range,
  className,
}: {
  spark: (string | null)[]
  best: string | null
  target: string | null
  currency: string
  range: TimeRange
  className?: string
}) {
  const bestN = best != null ? Number(best) : null
  const targetN = target != null ? Number(target) : null
  if (bestN == null || targetN == null || !Number.isFinite(bestN) || !Number.isFinite(targetN)) {
    return null
  }

  const sparkValues = spark
    .map((v) => (v == null ? null : Number(v)))
    .filter((v): v is number => v != null && Number.isFinite(v))
  const high = Math.max(...sparkValues, bestN)
  const inRange = bestN <= targetN

  // Hunting: scale high→target, tick at the right end, marker inside.
  // In range: scale high→best, marker at the right end, tick left of it.
  const rightEnd = inRange ? bestN : targetN
  const span = high - rightEnd
  if (!(span > 0)) return null
  const pos = (value: number) => Math.max(0, Math.min(1, (high - value) / span)) * 100
  const markerPos = pos(bestN)
  const targetPos = pos(targetN)
  const highLabel = `${RANGE_LABELS[range]} high ${formatMoney(high.toFixed(2), currency)}`
  const targetLabel = `⌖ ${formatMoney(target, currency)} ·`

  return (
    <div className={cn('w-full max-w-90', className)}>
      <div
        className="relative h-5.5"
        style={{
          backgroundImage:
            'linear-gradient(var(--color-hairline-strong), var(--color-hairline-strong)), repeating-linear-gradient(90deg, var(--color-hairline-strong) 0 1px, transparent 1px 10%)',
          backgroundSize: '100% 1px, 100% 6px',
          backgroundPosition: '0 11px, 0 8px',
          backgroundRepeat: 'no-repeat',
        }}
      >
        <span
          aria-hidden
          className="absolute top-0.5 h-4.5 w-0.5 bg-drop/45"
          style={{ left: `${targetPos}%` }}
        />
        <span
          aria-hidden
          className={cn(
            'absolute top-1 h-3.5 w-0.5',
            inRange ? 'bg-drop shadow-[0_0_8px_rgb(66_208_124_/_0.7)]' : 'bg-lume shadow-[0_0_8px_rgb(255_180_84_/_0.6)]',
          )}
          style={{ left: `${markerPos}%` }}
        />
      </div>
      <LadderLabels
        inRange={inRange}
        markerPos={markerPos}
        targetPos={targetPos}
        highLabel={highLabel}
        targetLabel={targetLabel}
        best={best}
        target={target}
        currency={currency}
      />
    </div>
  )
}

/**
 * The ladder's label line. Its own component so the row it measures exists
 * from mount: Ladder renders nothing until it has a best price and a target.
 */
function LadderLabels({
  inRange,
  markerPos,
  targetPos,
  highLabel,
  targetLabel,
  best,
  target,
  currency,
}: {
  inRange: boolean
  markerPos: number
  targetPos: number
  highLabel: string
  targetLabel: string
  best: string | null
  target: string | null
  currency: string
}) {
  const { ref, width } = useMeasuredWidth()
  const nowLabel = `now ${formatMoney(best, currency)}`
  const huntTargetLabel = `⌖ target ${formatMoney(target, currency)}`
  const joins = inRange
    ? ladderLabelJoins(Math.max(targetPos, 42), 'end', targetLabel, highLabel, `${nowLabel} ⌖`, width)
    : ladderLabelJoins(Math.max(46, markerPos), 'center', nowLabel, highLabel, huntTargetLabel, width)
  return (
    <div
      ref={ref}
      className={cn('relative mt-1 font-mono text-[12px] leading-4', joins ? 'flex flex-wrap gap-x-2' : 'h-4')}
    >
      <span className={cn('whitespace-nowrap text-ink-3', !joins && 'absolute left-0')}>{highLabel}</span>
      {/* Where the positioned label would overprint a neighbour, the pair
          collapses into a single right-anchored phrase instead; the line wraps,
          so a phrase too long to share it with the high label drops beneath it. */}
      {inRange ? (
        joins ? (
          <span className="ml-auto whitespace-nowrap text-drop">
            <span className="text-drop/60">⌖ {formatMoney(target, currency)}{' · '}</span>
            {nowLabel} ⌖
          </span>
        ) : (
          <>
            <span
              className="absolute -translate-x-full whitespace-nowrap text-drop/60"
              style={{ left: `${Math.max(targetPos, 42)}%` }}
            >
              {targetLabel}
            </span>
            <span className="absolute right-0 whitespace-nowrap text-drop">
              {nowLabel} ⌖
            </span>
          </>
        )
      ) : joins ? (
        <span className="ml-auto whitespace-nowrap">
          <span className="text-lume">{nowLabel}</span>
          <span className="text-drop">{' · '}{huntTargetLabel}</span>
        </span>
      ) : (
        <>
          <span
            className="absolute -translate-x-1/2 whitespace-nowrap text-lume"
            style={{ left: `${Math.max(46, markerPos)}%` }}
          >
            {nowLabel}
          </span>
          <span className="absolute right-0 whitespace-nowrap text-drop">
            {huntTargetLabel}
          </span>
        </>
      )}
    </div>
  )
}
