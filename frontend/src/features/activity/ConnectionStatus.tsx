import { cn } from '@/lib/cn'
import type { Connection } from './liveStream'

/** What each state means to someone wondering whether the prices are current. */
const DESCRIPTIONS: Record<Connection, string> = {
  connecting: 'Connecting to live updates…',
  live: 'Live: prices update as the hunter checks them',
  reconnecting: 'Reconnecting: prices may be out of date',
  paused: 'Live updates paused: prices may be out of date. Reload to reconnect.',
}

/** The live feed's state as a dot alone. */
export function ConnectionDot({ connection, className }: { connection: Connection; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'size-1.5 shrink-0 rounded-full',
        connection === 'connecting' && 'animate-pulse bg-ink-3',
        connection === 'live' && 'bg-drop',
        connection === 'reconnecting' && 'animate-pulse bg-warn',
        connection === 'paused' && 'bg-warn',
        className,
      )}
    />
  )
}

/**
 * The live feed's state as a dot and a word. `paused` means the stream has
 * been refused long enough that waiting is unlikely to help, so it offers the
 * one fix a person can make: a reload, which signs them in again if it must.
 */
export function ConnectionStatus({ connection }: { connection: Connection }) {
  return (
    <span className="flex items-center gap-1.5">
      <ConnectionDot connection={connection} />
      {connection === 'connecting' ? 'connecting…' : null}
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

/**
 * The masthead's quiet form: a dot while all is well, a word once it isn't,
 * since every page shows prices and only the Activity page has room to say
 * more. A paused feed becomes the reload button.
 */
export function MastheadConnection({ connection }: { connection: Connection }) {
  const description = DESCRIPTIONS[connection]
  const label = connection === 'paused' ? 'offline' : connection === 'reconnecting' ? 'reconnecting' : null
  const content = (
    <>
      <ConnectionDot connection={connection} />
      {label ? <span className="hidden sm:inline">{label}</span> : null}
    </>
  )
  const className =
    'flex min-h-6 min-w-6 items-center justify-center gap-1.5 font-mono text-[10.5px] tracking-[0.08em] text-warn uppercase'
  if (connection === 'paused') {
    return (
      <button
        type="button"
        onClick={() => window.location.reload()}
        title={description}
        aria-label={description}
        className={cn(className, 'hover:underline hover:underline-offset-2')}
      >
        {content}
      </button>
    )
  }
  return (
    <span title={description} className={className}>
      <span className="sr-only">{description}</span>
      {content}
    </span>
  )
}
