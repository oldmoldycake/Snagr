import type { AuthenticityRead, AuthenticityVerdict } from '@/api/types'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'
import { relativeTime } from '@/lib/time'

/**
 * The asymmetry-verbatim copy (D-V5): matching known fakes condemns (scam
 * listings reuse stolen photos of genuine items), matching known-real
 * references merely reassures — never "verified authentic".
 */
const VERDICT_COPY: Record<AuthenticityVerdict, string> = {
  leans_fake: 'photos consistent with known fakes',
  leans_real: 'photos match known-real references',
  inconclusive: 'photo check inconclusive',
}

/**
 * Title-line chip for the listings board. Health is silence — only
 * `leans_fake` earns a chip; the other verdicts live in the expanded row.
 */
export function AuthenticityChip({ read }: { read: AuthenticityRead }) {
  if (read.verdict !== 'leans_fake') return null
  return (
    <SimpleTooltip content={<span className="max-w-64">{VERDICT_COPY.leans_fake}</span>}>
      <Badge variant="rise" className="shrink-0 font-mono text-[10px] tnum">
        ✗ photos·fakes{read.fake_confidence != null ? ` ${read.fake_confidence}` : ''}
      </Badge>
    </SimpleTooltip>
  )
}

function ConfidenceMeter({ value, hot }: { value: string; hot: boolean }) {
  const fill = Math.max(0, Math.min(1, Number(value)))
  return (
    <span
      aria-hidden
      className="inline-block h-1 w-14 overflow-hidden rounded-full bg-raised align-middle"
    >
      <span
        className={cn('block h-full rounded-full', hot ? 'bg-rise' : 'bg-ink-3')}
        style={{ width: `${(fill * 100).toFixed(0)}%` }}
      />
    </span>
  )
}

/** Inline detail line for an expanded listing row — verdict copy, confidence meter, photo count. */
export function AuthenticityLine({ read }: { read: AuthenticityRead }) {
  const hot = read.verdict === 'leans_fake'
  return (
    <>
      <span className={cn(hot ? 'text-rise' : read.verdict === 'leans_real' && 'text-ink-2')}>
        {hot ? '✗ ' : ''}
        {VERDICT_COPY[read.verdict]}
      </span>
      {read.fake_confidence != null ? (
        <>
          {' · fake confidence '}
          <span className={cn('tnum', hot ? 'text-rise' : 'text-ink-2')}>{read.fake_confidence}</span>{' '}
          <ConfidenceMeter value={read.fake_confidence} hot={hot} />
        </>
      ) : null}
      {' · '}
      {read.image_count} {read.image_count === 1 ? 'photo' : 'photos'} · scanned{' '}
      {relativeTime(read.checked_at)}
    </>
  )
}
