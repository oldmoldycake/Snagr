import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

const unauthenticated = () =>
  new Response(JSON.stringify({ error: { code: 'unauthenticated', message: 'Not signed in' } }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })

/** Stubs fetch: every path answers from `routes`, each entry used once, in order. */
function stubFetch(routes: Record<string, (() => Response)[]>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    const next = routes[path]?.shift()
    if (!next) throw new Error(`unexpected fetch: ${path}`)
    return next()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const paths = (fetchMock: ReturnType<typeof stubFetch>) => fetchMock.mock.calls.map(([input]) => String(input))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api', () => {
  it('refreshes and retries /api/auth/me once the access cookie has expired', async () => {
    const fetchMock = stubFetch({
      '/api/auth/me': [unauthenticated, () => Response.json({ id: 'u1' })],
      '/api/auth/refresh': [() => new Response(null, { status: 204 })],
    })

    await expect(api('/api/auth/me')).resolves.toEqual({ id: 'u1' })
    expect(paths(fetchMock)).toEqual(['/api/auth/me', '/api/auth/refresh', '/api/auth/me'])
  })

  it('gives up with the 401 when the refresh is refused too', async () => {
    const fetchMock = stubFetch({
      '/api/items': [unauthenticated],
      '/api/auth/refresh': [unauthenticated],
    })

    await expect(api('/api/items')).rejects.toMatchObject({ status: 401, code: 'unauthenticated' })
    expect(paths(fetchMock)).toEqual(['/api/items', '/api/auth/refresh'])
  })

  it.each(['/api/auth/login', '/api/auth/register', '/api/auth/logout', '/api/auth/invites/abc/accept'])(
    'never refreshes on a 401 from %s, so a refused credential is not replayed',
    async (path) => {
      const fetchMock = stubFetch({ [path]: [unauthenticated] })

      await expect(api(path, { method: 'POST', body: {} })).rejects.toBeInstanceOf(ApiError)
      expect(paths(fetchMock)).toEqual([path])
    },
  )
})
