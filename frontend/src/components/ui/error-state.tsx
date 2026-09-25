import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from './button'

/**
 * A load that failed, in the empty state's frame but never in its words: the
 * ⚠ glyph in rise, what didn't load, the server's reason, and Retry. Pages
 * check for it before their empty and not-found branches, so a 500 is never
 * read as "your data is gone".
 */
export function ErrorState({
  title = "Couldn't load this",
  error,
  onRetry,
  retrying = false,
  className,
}: {
  title?: string
  error: Error | null
  onRetry: () => void
  retrying?: boolean
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-rise/40 px-6 py-12 text-center',
        className,
      )}
    >
      <span aria-hidden className="font-display text-2xl text-rise">
        ⚠
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="max-w-sm text-[13px] text-ink-2">The request failed — nothing here is missing or deleted.</p>
      {error ? <p className="max-w-sm font-mono text-[11px] text-ink-3">{error.message}</p> : null}
      <div className="mt-2">
        <Button size="sm" onClick={onRetry} disabled={retrying}>
          {retrying ? <Loader2 className="animate-spin" /> : null}
          Retry
        </Button>
      </div>
    </div>
  )
}
