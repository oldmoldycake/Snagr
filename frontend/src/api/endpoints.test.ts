import { afterEach, describe, expect, it, vi } from 'vitest'
import { acceptInvite, validateInvite } from './endpoints'

/** Stubs fetch to answer every request with `body`, recording the paths it was asked for. */
function stubFetch(body: unknown) {
  const fetchMock = vi.fn(async () => Response.json(body))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const paths = (fetchMock: ReturnType<typeof stubFetch>) =>
  fetchMock.mock.calls.map((call: unknown[]) => String(call[0]))

afterEach(() => {
  vi.unstubAllGlobals()
})

// The token comes straight from the /invite/:token URL, so a crafted link must not be able
// to point these requests (and the visitor's cookies) at another route.
describe('invite endpoints', () => {
  const token = '../../admin/invites#'

  it('encodes the token when validating an invite', async () => {
    const fetchMock = stubFetch({ email: null, expires_at: '2026-01-01T00:00:00Z' })

    await validateInvite(token)
    expect(paths(fetchMock)).toEqual(['/api/auth/invites/..%2F..%2Fadmin%2Finvites%23'])
  })

  it('encodes the token when accepting an invite', async () => {
    const fetchMock = stubFetch({ user: {} })

    await acceptInvite(token, { email: 'a@b.c', password: 'hunter22hunter22' })
    expect(paths(fetchMock)).toEqual(['/api/auth/invites/..%2F..%2Fadmin%2Finvites%23/accept'])
  })
})
