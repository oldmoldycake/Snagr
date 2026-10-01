import { useMeasuredWidth } from '@/components/charts/pricePlot'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { RANGE_LABELS, type TimeRange } from '@/lib/time'
import { ladderTargetJoinsNow } from './ladderLabels'

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
  return (
    <div ref={ref} className="relative mt-1 h-4 font-mono text-[12px]">
      <span className="absolute left-0 text-ink-3">{highLabel}</span>
      {/* Where the positioned label would overprint a neighbour (best ≈ target
          on the right, a target at or above the high on the left), the pair
          collapses into a single right-anchored phrase instead. */}
      {inRange ? (
        ladderTargetJoinsNow(targetPos, targetLabel, highLabel, width) ? (
          <span className="absolute right-0 whitespace-nowrap text-drop">
            <span className="text-drop/60">⌖ {formatMoney(target, currency)}{' · '}</span>
            now {formatMoney(best, currency)} ⌖
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
              now {formatMoney(best, currency)} ⌖
            </span>
          </>
        )
      ) : markerPos > 55 ? (
        <span className="absolute right-0 whitespace-nowrap">
          <span className="text-lume">now {formatMoney(best, currency)}</span>
          <span className="text-drop">{' · '}⌖ target {formatMoney(target, currency)}</span>
        </span>
      ) : (
        <>
          <span
            className="absolute -translate-x-1/2 whitespace-nowrap text-lume"
            style={{ left: `${Math.max(46, markerPos)}%` }}
          >
            now {formatMoney(best, currency)}
          </span>
          <span className="absolute right-0 whitespace-nowrap text-drop">
            ⌖ target {formatMoney(target, currency)}
          </span>
        </>
      )}
    </div>
  )
}
