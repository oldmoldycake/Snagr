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
