import type { ApiErrorBody } from './types'

export class ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string>
  runId?: number

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error.message ?? `Request failed (${status})`)
    this.status = status
    this.code = body?.error.code ?? 'unknown'
    this.fields = body?.error.fields
    this.runId = body?.error.run_id
  }
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

export interface RequestOptions {
  method?: Method
  body?: unknown
  params?: Record<string, string | number | boolean | undefined>
  signal?: AbortSignal
}

/**
 * Auth lives in httpOnly cookies, so "logged in" is invisible to JS — we just
 * send requests and react to 401s: refresh once (single-flight across all
 * concurrent requests), retry once, then give up and let the caller redirect.
 */
let refreshPromise: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
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

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  let res = await doFetch(path, opts)

  if (res.status === 401 && !path.startsWith('/api/auth/')) {
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
