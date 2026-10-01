import { cn } from '@/lib/cn'
import type { Connection } from './liveStream'

/**
 * The live feed's state as a dot and a word. `paused` means the stream has
 * been refused long enough that waiting is unlikely to help, so it offers the
 * one fix a person can make: a reload, which signs them in again if it must.
 */
export function ConnectionStatus({ connection }: { connection: Connection }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden
        className={cn(
          'size-1.5 rounded-full',
          connection === 'live' && 'bg-drop',
          connection === 'reconnecting' && 'animate-pulse bg-warn',
          connection === 'paused' && 'bg-warn',
        )}
      />
      {connection === 'live' ? 'live' : null}
      {connection === 'reconnecting' ? 'reconnecting…' : null}
      {connection === 'paused' ? (
        <>
          <span className="text-warn">Live updates paused</span>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="text-ink-2 underline underline-offset-2 hover:text-ink"
          >
            Reload
          </button>
        </>
      ) : null}
    </span>
  )
}
