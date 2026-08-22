import { SimpleTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'

/**
 * 0–100 criteria-fit score, tinted by band. The agent's one-line rationale
 * lives in the tooltip.
 */
export function MatchPill({ score, summary }: { score: number | null; summary: string | null }) {
  if (score == null) return <span className="text-xs text-ink-3">—</span>

  const band =
    score >= 85
      ? 'border-drop/40 bg-drop/10 text-drop'
      : score >= 70
        ? 'border-lume/40 bg-lume-glow text-lume'
        : 'border-hairline-strong bg-transparent text-ink-3'

  const pill = (
    <span
      className={cn(
        'inline-flex min-w-8 items-center justify-center rounded-full border px-1.5 py-0.5 font-mono text-[11px] font-medium tnum',
        band,
      )}
    >
      {score}
    </span>
  )

  return summary ? (
    <SimpleTooltip content={<span className="max-w-64">{summary}</span>}>{pill}</SimpleTooltip>
  ) : (
    pill
  )
}
