/**
 * Prices travel through the API as decimal strings ("549.99") to avoid float
 * drift. Formatting works on the string; arithmetic goes through cents.
 */

const SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  CAD: 'CA$',
}

export function formatMoney(price: string | null | undefined, currency = 'USD'): string {
  if (price == null) return '—'
  const symbol = SYMBOLS[currency] ?? `${currency} `
  const n = Number(price)
  if (!Number.isFinite(n)) return '—'
  return `${symbol}${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function toCents(price: string | null | undefined): number | null {
  if (price == null) return null
  const n = Number(price)
  return Number.isFinite(n) ? Math.round(n * 100) : null
}

export function fromCents(cents: number): string {
  return (cents / 100).toFixed(2)
}

/** Signed percent between two decimal strings: pctChange("500", "550") → "+10.0" */
export function pctChange(from: string, to: string): string | null {
  const a = Number(from)
  const b = Number(to)
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return null
  const pct = ((b - a) / a) * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}`
}
