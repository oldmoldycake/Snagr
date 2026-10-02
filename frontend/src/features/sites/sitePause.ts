import type { Site } from '@/api/types'

/** Whether the circuit breaker is holding this site now. A pause lifts on its
 *  own once `paused_until` passes, so a past one no longer counts. */
export function isPaused(site: Site, now: number = Date.now()): boolean {
  return site.paused_until != null && new Date(site.paused_until).getTime() > now
}
