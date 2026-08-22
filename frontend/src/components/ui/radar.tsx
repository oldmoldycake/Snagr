import { cn } from '@/lib/cn'

/**
 * The radar — proof the agent is prowling. Sweeps only while a run is live;
 * idle (or reduced motion) shows the static wedge. Decorative: always paired
 * with a text state ("Sweeping…", "Idle") by the caller.
 */
export function Radar({
  size = 24,
  animate = true,
  glyph = false,
  className,
}: {
  size?: number
  animate?: boolean
  glyph?: boolean
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'relative block shrink-0 overflow-hidden rounded-full border border-hairline-strong',
        className,
      )}
      style={{ width: size, height: size }}
    >
      <span
        className={cn('absolute inset-0', animate && 'animate-sweep')}
        style={{ background: 'conic-gradient(from 0deg, rgb(255 180 84 / 0.5), transparent 75deg)' }}
      />
      {glyph ? (
        <span
          className="absolute inset-0 grid place-items-center text-lume"
          style={{ fontSize: Math.round(size * 0.3) }}
        >
          ⌖
        </span>
      ) : null}
    </span>
  )
}
