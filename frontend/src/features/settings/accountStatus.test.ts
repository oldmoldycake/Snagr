import { describe, expect, it } from 'vitest'
import { accountStatusReceipt } from './accountStatus'

describe('accountStatusReceipt', () => {
  it('says a deactivated user is locked out', () => {
    expect(accountStatusReceipt('sam@example.com', false)).toBe(
      "Deactivated sam@example.com — they're signed out and can't sign back in",
    )
  })

  it('says a reactivated user can sign in again', () => {
    expect(accountStatusReceipt('sam@example.com', true)).toBe('Reactivated sam@example.com — they can sign in again')
  })
})
