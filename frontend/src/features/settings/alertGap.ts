import { useQuery } from '@tanstack/react-query'
import { listChannels } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { NotificationChannel } from '@/api/types'

/** Why an item reaching its target would alert no one: no channel at all, or none switched on for it. */
export type AlertGap = 'no-channels' | 'none-on'

/**
 * The backend sends a target hit to every enabled channel whose events
 * include it (null is all of them) and quietly skips it when none does, so
 * that is the only rule that says whether an at-target alert reaches anyone.
 * Null when one will.
 */
export function targetAlertGap(channels: NotificationChannel[]): AlertGap | null {
  if (channels.length === 0) return 'no-channels'
  const delivers = channels.some((c) => c.enabled && (c.events == null || c.events.includes('target.hit')))
  return delivers ? null : 'none-on'
}

/**
 * targetAlertGap over the caller's channels. Null until they load, and if
 * they can't: a warning that alerts go nowhere is only worth showing when
 * it's known to be true.
 */
export function useTargetAlertGap(): AlertGap | null {
  const channels = useQuery({ queryKey: qk.channels, queryFn: listChannels })
  return channels.data ? targetAlertGap(channels.data.data) : null
}
