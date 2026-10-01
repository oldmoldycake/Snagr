import { tryRefresh } from '@/api/client'

export type Connection = 'live' | 'reconnecting'

const FIRST_RETRY_MS = 1_000
const MAX_RETRY_MS = 30_000

/**
 * Open an EventSource that outlives the browser's own reconnect. A dropped
 * connection leaves the source CONNECTING and the browser retries it; any
 * non-200 answer to that retry — the 401 of an access cookie that expired
 * while the tab slept — closes it for good. So a CLOSED source is replaced:
 * refresh the session, then open a new one, backing off while it keeps
 * failing. `listen` wires each new source; returns the teardown.
 */
export function openLiveStream(
  url: string,
  listen: (source: EventSource) => void,
  onConnection: (connection: Connection) => void,
): () => void {
  let source: EventSource
  let retryMs = FIRST_RETRY_MS
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false

  const connect = () => {
    source = new EventSource(url)
    source.onopen = () => {
      retryMs = FIRST_RETRY_MS
      onConnection('live')
    }
    source.onerror = () => {
      onConnection('reconnecting')
      if (source.readyState !== EventSource.CLOSED) return
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
