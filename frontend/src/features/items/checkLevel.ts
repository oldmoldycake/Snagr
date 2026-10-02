import type { PriceCheck } from '@/api/types'
import type { LogGlyphLevel } from '@/components/ui/terminal-log'

/**
 * The mark a recent check gets. A green ✓ means a price you could buy at, so
 * an out-of-stock reading takes the neutral mark: the check worked, but there
 * is nothing to snag. A failed check warns; a listing that sold or ended is
 * gone for good.
 */
export function checkLevel(check: PriceCheck): LogGlyphLevel {
  if (check.status === 'sold' || check.status === 'ended') return 'error'
  if (check.status === 'error') return 'warn'
  if (check.status === 'ok') return check.in_stock === false ? 'info' : 'success'
  return 'info'
}
