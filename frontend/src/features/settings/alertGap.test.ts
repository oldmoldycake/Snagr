import { describe, expect, it } from 'vitest'
import type { NotificationChannel } from '@/api/types'
import { targetAlertGap } from './alertGap'

function channel(enabled: boolean, events: NotificationChannel['events']): NotificationChannel {
  return { id: 1, kind: 'ntfy', name: 'phone', enabled, events } as NotificationChannel
}

describe('targetAlertGap', () => {
  it('says there is no channel when the account has none', () => {
    expect(targetAlertGap([])).toBe('no-channels')
  })

  it('is satisfied by an enabled channel that takes every event', () => {
    expect(targetAlertGap([channel(true, null)])).toBeNull()
  })

  it('is satisfied by an enabled channel that takes at-target alerts', () => {
    expect(targetAlertGap([channel(true, ['target.hit'])])).toBeNull()
  })

  it('does not count a channel that is switched off', () => {
    expect(targetAlertGap([channel(false, null)])).toBe('none-on')
  })

  it('does not count a channel that only takes new listings', () => {
    expect(targetAlertGap([channel(true, ['listing.new']), channel(false, ['target.hit'])])).toBe('none-on')
  })

  it('needs only one channel that delivers', () => {
    expect(targetAlertGap([channel(false, null), channel(true, ['listing.new']), channel(true, null)])).toBeNull()
  })
})
