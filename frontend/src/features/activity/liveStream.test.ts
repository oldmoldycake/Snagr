import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openLiveStream, type Connection } from './liveStream'

/** Just enough EventSource to drive: the test decides when it opens or fails. */
class FakeEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static opened: FakeEventSource[] = []

  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn(() => {
    this.readyState = FakeEventSource.CLOSED
  })

  constructor() {
    FakeEventSource.opened.push(this)
  }

  open() {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }

  /** A dropped connection the browser will retry by itself. */
  drop() {
    this.readyState = FakeEventSource.CONNECTING
    this.onerror?.()
  }

  /** A non-200 answer (a 401): the browser never retries this one. */
  refuse() {
    this.readyState = FakeEventSource.CLOSED
    this.onerror?.()
  }
}

let fetchMock: ReturnType<typeof vi.fn>
const sources = () => FakeEventSource.opened

function open() {
  const connections: Connection[] = []
  const listen = vi.fn()
  const stop = openLiveStream('/api/events', listen, (c) => connections.push(c))
  return { connections, listen, stop }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.opened = []
  vi.stubGlobal('EventSource', FakeEventSource)
  fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('openLiveStream', () => {
  it('leaves a dropped connection to the browser', async () => {
    const { connections } = open()
    sources()[0].open()
    sources()[0].drop()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(connections).toEqual(['live', 'reconnecting'])
    expect(sources()).toHaveLength(1)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('refreshes the session and opens a new stream once the browser gives up', async () => {
    const { connections, listen } = open()
    sources()[0].open()
    sources()[0].refuse()

    await vi.advanceTimersByTimeAsync(1_000)
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/refresh', expect.objectContaining({ method: 'POST' }))
    expect(sources()).toHaveLength(2)
    expect(listen).toHaveBeenLastCalledWith(sources()[1])

    sources()[1].open()
    expect(connections).toEqual(['live', 'reconnecting', 'live'])
  })

  it('backs off while the new streams keep failing, and resets once one opens', async () => {
    open()
    sources()[0].refuse()
    await vi.advanceTimersByTimeAsync(1_000)
    sources()[1].refuse()
    await vi.advanceTimersByTimeAsync(1_999)
    expect(sources()).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(sources()).toHaveLength(3)

    sources()[2].open()
    sources()[2].refuse()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(sources()).toHaveLength(4)
  })

  it('still reconnects when the refresh itself fails', async () => {
    fetchMock.mockRejectedValue(new TypeError('network down'))
    open()
    sources()[0].refuse()

    await vi.advanceTimersByTimeAsync(1_000)
    expect(sources()).toHaveLength(2)
  })

  it('reads paused after five refusals in a row, keeps retrying, and recovers', async () => {
    const { connections } = open()
    for (let i = 0; i < 4; i++) {
      sources()[i].refuse()
      await vi.advanceTimersByTimeAsync(30_000)
    }
    expect(connections.at(-1)).toBe('reconnecting')

    sources()[4].refuse()
    expect(connections.at(-1)).toBe('paused')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(sources()).toHaveLength(6)

    // a drop the browser retries by itself doesn't hide that the stream was paused
    sources()[5].drop()
    expect(connections.at(-1)).toBe('paused')

    sources()[5].open()
    expect(connections.at(-1)).toBe('live')
    sources()[5].refuse()
    expect(connections.at(-1)).toBe('reconnecting')
  })

  it('opens nothing more once stopped', async () => {
    const { stop } = open()
    sources()[0].refuse()
    stop()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(sources()).toHaveLength(1)
    expect(sources()[0].close).toHaveBeenCalled()
  })
})
