import type { ApiErrorBody } from './types'

/**
 * A non-2xx response, carrying the status and the error envelope's `code` and `fields`
 * (`code` is "unknown" when the body was not the envelope).
 */
export class ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string>

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error.message ?? `Something went wrong (error ${status}). Try again, and tell your admin if it keeps happening.`)
    this.status = status
    this.code = body?.error.code ?? 'unknown'
    this.fields = body?.error.fields
  }
}

/** True only for a 404: any other failure is an error to show, never "not found". */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

/**
 * Per-call options for `api`: `params` become the query string (undefined values dropped),
 * and a FormData `body` is sent as multipart rather than JSON.
 */
export interface RequestOptions {
  method?: Method
  body?: unknown
  params?: Record<string, string | number | boolean | undefined>
  signal?: AbortSignal
}

/**
 * Auth lives in httpOnly cookies, so "logged in" is invisible to JS — we just
 * send requests and react to 401s: refresh once (single-flight across all
 * concurrent requests), retry once, then give up and throw: the query and
 * mutation caches in main.tsx send a signed-in visitor back to /login.
 */
let refreshPromise: Promise<boolean> | null = null

/** Rotate the session cookies; true when the server issued fresh ones. */
export async function tryRefresh(): Promise<boolean> {
  refreshPromise ??= fetch('/api/auth/refresh', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Snagr-Csrf': '1' },
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

const NO_REFRESH = [
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/refresh',
  '/api/auth/logout',
  '/api/auth/invites/',
]

function buildUrl(path: string, params?: RequestOptions['params']): string {
  if (!params) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${path}?${qs}` : path
}

async function doFetch(path: string, opts: RequestOptions): Promise<Response> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-Snagr-Csrf'] = '1'
  // FormData passes through untouched — the browser sets the multipart
  // boundary itself, and a forced Content-Type would break it
  const isForm = opts.body instanceof FormData
  if (opts.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  return fetch(buildUrl(path, opts.params), {
    method,
    headers,
    credentials: 'same-origin',
    body:
      opts.body === undefined
        ? undefined
        : opts.body instanceof FormData
          ? opts.body
          : JSON.stringify(opts.body),
    signal: opts.signal,
  })
}

/**
 * Fetch a same-origin API path and parse the JSON (undefined for a 204); any error
 * status throws ApiError. Adds the CSRF header to every mutation.
 */
export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  let res = await doFetch(path, opts)

  // The credential routes answer 401 directly and must not trip this loop: a
  // failed login would otherwise refresh and silently replay itself. /me is not
  // one of them — it is the first request of every page load, so a 401 there
  // usually just means the short-lived access cookie expired.
  if (res.status === 401 && !NO_REFRESH.some((prefix) => path.startsWith(prefix))) {
    const refreshed = await tryRefresh()
    if (refreshed) res = await doFetch(path, opts)
  }

  if (!res.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await res.json()) as ApiErrorBody
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, body)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
