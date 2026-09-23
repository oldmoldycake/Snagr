export type TimeRange = '7d' | '30d' | '90d' | '1y' | 'all'

export const TIME_RANGES: TimeRange[] = ['7d', '30d', '90d', '1y', 'all']

export const RANGE_LABELS: Record<TimeRange, string> = {
  '7d': '7d',
  '30d': '30d',
  '90d': '90d',
  '1y': '1y',
  all: 'All',
}

export function rangeToMs(range: TimeRange): number {
  const day = 86_400_000
  switch (range) {
    case '7d':
      return 7 * day
    case '30d':
      return 30 * day
    case '90d':
      return 90 * day
    case '1y':
      return 365 * day
    case 'all':
      return Number.POSITIVE_INFINITY
  }
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return '—'
  const diff = Date.now() - then
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function formatDuration(startIso: string | null, endIso?: string | null): string {
  if (!startIso) return '—'
  const start = new Date(startIso).getTime()
  const end = endIso ? new Date(endIso).getTime() : Date.now()
  const secs = Math.max(0, Math.floor((end - start) / 1000))
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

/** A check interval the way the facts line says it: `30m`, `1h`, `6h`, `1h 30m`. */
export function formatInterval(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const rest = minutes % 60
  return rest === 0 ? `${minutes / 60}h` : `${Math.floor(minutes / 60)}h ${rest}m`
}

/** Axis tick formatter per range: 7d/30d → "Jun 24", 90d+ → "Jun '26" */
export function tickFormatterFor(range: TimeRange): (ts: number) => string {
  return (ts: number) => {
    const d = new Date(ts)
    if (range === '7d' || range === '30d') {
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    }
    return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' }).replace(' ', " '")
  }
}

/**
 * How long until something happens, the way the Activity page says it:
 * under a minute `in 0:42`, under an hour `in 12m`, under a day `in 2h` or
 * `in 4h 12m`, and beyond that the clock time — a countdown in days is a
 * date, not a countdown.
 */
export function countdown(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return '—'
  const secs = Math.round((then - Date.now()) / 1000)
  if (secs <= 0) return 'now'
  if (secs < 60) return `in 0:${String(secs).padStart(2, '0')}`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `in ${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours >= 24) return clockTime(iso)
  const rest = mins % 60
  return rest === 0 ? `in ${hours}h` : `in ${hours}h ${rest}m`
}

/** `15:04`, or `yesterday` / `Sep 18` once it is not today's clock. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso)
  if (!Number.isFinite(then.getTime())) return '—'
  const today = new Date()
  if (then.toDateString() === today.toDateString()) {
    return then.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
  }
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (then.toDateString() === yesterday.toDateString()) return 'yesterday'
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** `14:02:11` — the timestamp every log line carries. */
export function logTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** `12.4k` — token counts are read at a glance, never audited. */
export function formatTokens(n: number): string {
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(1)}k`
}

/** `1.8s` — how long one job took. */
export function formatMillis(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  const secs = ms / 1000
  if (secs < 60) return `${secs < 10 ? secs.toFixed(1) : Math.round(secs)}s`
  return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`
}
