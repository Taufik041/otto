import { ApiError, errorFrom } from './errors'
import type { Me, TokenBody } from './types'

/**
 * The API client and the signed-in state.
 *
 * - The access token lives only in this closure (never in storage) and goes out as
 *   `Authorization: Bearer`. Every request also sends cookies (`credentials: "include"`): the
 *   refresh cookie reaches /auth/refresh and /auth/logout only (Path=/auth).
 * - Refresh is single-flight: one promise per tab, and navigator.locks across tabs, so two tabs
 *   don't rotate the same refresh cookie at once.
 * - A 401 refreshes once and retries the request once. A refresh the gateway refuses signs out.
 * - A new token schedules the next refresh about a minute before it expires.
 */

export type AuthStatus = 'loading' | 'signedIn' | 'signedOut'
export type AuthState = { status: AuthStatus; user: Me | null }

export type RequestOptions = {
  method?: string
  body?: unknown
  signal?: AbortSignal
  /** false: a 401 is the answer (wrong password), not an expired token */
  retry?: boolean
}

type Locks = Pick<LockManager, 'request'>

export type ClientDeps = {
  baseUrl: string
  fetch?: typeof fetch
  /** navigator.locks; null to skip the cross-tab lock */
  locks?: Locks | null
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (id: unknown) => void
}

export const REFRESH_LOCK = 'otto-refresh'
export const REFRESH_EARLY_SECONDS = 60

export function createClient(deps: ClientDeps) {
  const base = deps.baseUrl.replace(/\/+$/, '')
  const doFetch = deps.fetch ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init))
  const locks = deps.locks === undefined ? (globalThis.navigator?.locks ?? null) : deps.locks
  const setTimer = deps.setTimer ?? ((fn: () => void, ms: number) => setTimeout(fn, ms))
  const clearTimer = deps.clearTimer ?? ((id: unknown) => clearTimeout(id as ReturnType<typeof setTimeout>))

  let token: string | null = null
  let timer: unknown = null
  let inflight: Promise<TokenBody | null> | null = null
  let state: AuthState = { status: 'loading', user: null }
  const listeners = new Set<() => void>()

  function setState(next: AuthState) {
    state = next
    listeners.forEach((l) => l())
  }

  function schedule(expiresIn: number) {
    if (timer !== null) clearTimer(timer)
    const seconds = Math.max(expiresIn - REFRESH_EARLY_SECONDS, 5)
    timer = setTimer(() => {
      timer = null
      refresh().catch(() => {
        // offline: the next request's 401 refreshes again
      })
    }, seconds * 1000)
  }

  /** Keep the tokens from a sign-in, sign-up, refresh or password change. */
  function signIn(body: TokenBody) {
    token = body.access_token
    schedule(body.expires_in)
    setState({ status: 'signedIn', user: body.user })
  }

  function forget() {
    token = null
    if (timer !== null) clearTimer(timer)
    timer = null
    setState({ status: 'signedOut', user: null })
  }

  async function send(path: string, opts: RequestOptions, bearer: string | null): Promise<Response> {
    const headers: Record<string, string> = {}
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
    if (bearer) headers.Authorization = `Bearer ${bearer}`
    try {
      return await doFetch(base + path, {
        method: opts.method ?? 'GET',
        credentials: 'include',
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: opts.signal,
      })
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') throw e
      throw new ApiError(0, 'network error')
    }
  }

  async function refreshNow(): Promise<TokenBody | null> {
    const res = await send('/auth/refresh', { method: 'POST' }, null)
    if (res.status === 401 || res.status === 403) {
      forget()
      return null
    }
    if (!res.ok) throw await errorFrom(res)
    const body = (await res.json()) as TokenBody
    signIn(body)
    return body
  }

  /** A new access token from the refresh cookie; null (and signed out) if the gateway refuses it.
   *  Concurrent calls share one request, and tabs take turns. Network errors throw. */
  function refresh(): Promise<TokenBody | null> {
    if (!inflight) {
      const run = locks ? locks.request(REFRESH_LOCK, refreshNow) : refreshNow()
      inflight = Promise.resolve(run).finally(() => {
        inflight = null
      })
    }
    return inflight
  }

  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const sent = token
    let res = await send(path, opts, sent)
    if (res.status === 401 && opts.retry !== false) {
      if (!(token && token !== sent)) {
        // nobody refreshed while this was in flight: do it now
        const got = await refresh()
        if (!got) throw new ApiError(401, 'sign in again')
      }
      res = await send(path, opts, token)
      if (res.status === 401) {
        forget()
        throw await errorFrom(res)
      }
    }
    if (!res.ok) throw await errorFrom(res)
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  }

  /** On app load: restore the session from the refresh cookie. */
  async function restore() {
    try {
      await refresh()
    } catch {
      forget() // the gateway is down: show the sign-in page, which says so when it fails
    }
  }

  /** Sign this device out. The gateway may be unreachable; the token is dropped regardless. */
  async function logout() {
    try {
      await send('/auth/logout', { method: 'POST' }, null)
    } catch {
      // still signed out here; the refresh cookie expires by itself
    }
    forget()
  }

  /** Sign out every device, this one too. */
  async function logoutAll() {
    await request('/auth/logout-all', { method: 'POST' })
    forget()
  }

  return {
    request,
    refresh,
    restore,
    signIn,
    logout,
    logoutAll,
    /** Replace the signed-in user (after PATCH /me) without touching the token. */
    setUser(user: Me) {
      if (state.status === 'signedIn') setState({ status: 'signedIn', user })
    },
    getToken: () => token,
    getState: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}

export type Client = ReturnType<typeof createClient>
