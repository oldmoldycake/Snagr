import { tryRefresh } from '@/api/client'

export type Connection = 'live' | 'reconnecting' | 'paused'

const FIRST_RETRY_MS = 1_000
const MAX_RETRY_MS = 30_000
/** Five refused streams in a row is ~30 s of backoff: long enough that this is
 *  no blip, so the page says so and offers a reload. */
const PAUSE_AFTER = 5

/**
 * Open an EventSource that outlives the browser's own reconnect. A dropped
 * connection leaves the source CONNECTING and the browser retries it; any
 * non-200 answer to that retry — the 401 of an access cookie that expired
 * while the tab slept — closes it for good. So a CLOSED source is replaced:
 * refresh the session, then open a new one, backing off while it keeps
 * failing. After PAUSE_AFTER refusals in a row the connection reads `paused`;
 * the retries carry on, so a backend that comes back still heals the stream.
 * `listen` wires each new source; returns the teardown.
 */
export function openLiveStream(
  url: string,
  listen: (source: EventSource) => void,
  onConnection: (connection: Connection) => void,
): () => void {
  let source: EventSource
  let retryMs = FIRST_RETRY_MS
  let refusals = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false

  const connect = () => {
    source = new EventSource(url)
    source.onopen = () => {
      retryMs = FIRST_RETRY_MS
      refusals = 0
      onConnection('live')
    }
    source.onerror = () => {
      const closed = source.readyState === EventSource.CLOSED
      if (closed) refusals += 1
      onConnection(refusals >= PAUSE_AFTER ? 'paused' : 'reconnecting')
      if (!closed) return
      const delay = retryMs
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS)
      timer = setTimeout(() => {
        // reconnect whether or not the refresh took: a backend that is still
        // down fails both, and the next CLOSED backs off again
        void tryRefresh().then(() => {
          if (!stopped) connect()
        })
      }, delay)
    }
    listen(source)
  }

  connect()
  return () => {
    stopped = true
    clearTimeout(timer)
    source.close()
  }
}
