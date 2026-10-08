/**
 * Is Otto live? The landing page's status pill asks the gateway's GET /health (no sign-in): live
 * when Otto is up and its workers answer, offline otherwise, and when nothing answers within
 * TIMEOUT_MS. Asked again every REFRESH_MS. VITE_STATUS_OVERRIDE=up|down skips asking (a demo,
 * or the hardware is off for good).
 */
import { useEffect, useState } from 'react'

/** live: up, workers online; chat: up, workers offline (plain chat works); offline: unreachable or paused */
export type Status = 'checking' | 'live' | 'chat' | 'offline'
export type Override = 'auto' | 'up' | 'down'
type Fetch = (url: string, init?: RequestInit) => Promise<Response>

export const TIMEOUT_MS = 2_000
export const REFRESH_MS = 60_000

export function parseOverride(value: string | undefined): Override {
  const v = (value ?? '').trim().toLowerCase()
  return v === 'up' || v === 'down' ? v : 'auto'
}

export async function checkHealth(apiUrl: string, fetchFn: Fetch = fetch, timeoutMs = TIMEOUT_MS): Promise<'live' | 'chat' | 'offline'> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const res = await fetchFn(`${apiUrl.replace(/\/+$/, '')}/health`, { signal: abort.signal, credentials: 'omit', cache: 'no-store' })
    if (!res.ok) return 'offline'
    const body = (await res.json()) as { status?: unknown; workers?: unknown }
    if (body.status !== 'up') return 'offline' // paused: no new accounts
    return body.workers === 'online' ? 'live' : 'chat'
  } catch {
    return 'offline' // unreachable, timed out, or not JSON
  } finally {
    clearTimeout(timer)
  }
}

export function useStatus({ apiUrl, override, fetch: fetchFn = fetch }: { apiUrl: string; override: Override; fetch?: Fetch }): Status {
  const [status, setStatus] = useState<Status>(override === 'up' ? 'live' : override === 'down' ? 'offline' : 'checking')
  useEffect(() => {
    if (override !== 'auto') return
    let live = true
    const ask = () => void checkHealth(apiUrl, fetchFn).then((s) => live && setStatus(s))
    ask()
    const timer = setInterval(ask, REFRESH_MS)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [apiUrl, override, fetchFn])
  return status
}
