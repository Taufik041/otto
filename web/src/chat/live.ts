import type { SessionEvent } from './reduce'

/**
 * A session's events, live: load what's stored, then follow the WebSocket.
 *
 * Each (re)connect takes a fresh single-use ticket (POST /sessions/{id}/ws-ticket) and asks for
 * the events after the last seq it has, so nothing is missed across a drop; the reducer dedupes
 * by seq anyway. Drops reconnect with backoff (1s, 2s, 4s ... 15s). A closed session (4404) or
 * a refused ticket for a missing session stops for good.
 */

export type LiveState = 'connecting' | 'live' | 'reconnecting' | 'closed'

type SocketLike = {
  onopen: ((ev: unknown) => void) | null
  onmessage: ((ev: { data: unknown }) => void) | null
  onclose: ((ev: { code: number }) => void) | null
  onerror: ((ev: unknown) => void) | null
  close: (code?: number) => void
}

export type LiveDeps = {
  sessionId: string
  wsBase: string
  loadEvents: (afterSeq: number) => Promise<SessionEvent[]>
  ticket: () => Promise<string>
  onEvents: (events: SessionEvent[]) => void
  onState: (state: LiveState) => void
  /** the last seq the view has (read on every connect) */
  lastSeq: () => number
  WebSocket?: new (url: string) => SocketLike
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (id: unknown) => void
}

export const BACKOFF = [1000, 2000, 4000, 8000, 15000]
const GONE = 4404 // no such session (deleted)

export function backoff(attempt: number): number {
  return BACKOFF[Math.min(attempt, BACKOFF.length - 1)]!
}

export function followSession(deps: LiveDeps): () => void {
  const WS = deps.WebSocket ?? (globalThis.WebSocket as unknown as new (url: string) => SocketLike)
  const setTimer = deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms))
  const clearTimer = deps.clearTimer ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>))
  let stopped = false
  let socket: SocketLike | null = null
  let timer: unknown = null
  let attempt = 0

  const retry = () => {
    if (stopped) return
    deps.onState('reconnecting')
    timer = setTimer(() => {
      timer = null
      void connect()
    }, backoff(attempt++))
  }

  async function connect() {
    if (stopped) return
    let ticket: string
    try {
      // catch up over HTTP first: a reconnect shows what happened while away even if the socket
      // takes a while (the socket replays after after_seq too; duplicates are dropped by seq)
      deps.onEvents(await deps.loadEvents(deps.lastSeq()))
      ticket = await deps.ticket()
    } catch (e) {
      if ((e as { status?: number })?.status === 404) {
        stopped = true
        deps.onState('closed')
        return
      }
      retry()
      return
    }
    if (stopped) return
    const url = `${deps.wsBase}/sessions/${encodeURIComponent(deps.sessionId)}/ws?ticket=${encodeURIComponent(ticket)}&after_seq=${deps.lastSeq()}`
    const ws = new WS(url)
    socket = ws
    ws.onopen = () => {
      attempt = 0
      deps.onState('live')
    }
    ws.onmessage = (ev) => {
      let data: unknown
      try {
        data = JSON.parse(String(ev.data))
      } catch {
        return
      }
      const e = data as Partial<SessionEvent>
      if (typeof e?.seq === 'number' && typeof e.type === 'string') deps.onEvents([e as SessionEvent])
      // {"type": "ping"} keeps the connection open; nothing to do
    }
    ws.onerror = () => {
      // onclose follows
    }
    ws.onclose = (ev) => {
      if (socket !== ws) return
      socket = null
      if (stopped) return
      if (ev.code === GONE) {
        stopped = true
        deps.onState('closed')
        return
      }
      retry()
    }
  }

  deps.onState('connecting')
  void connect()
  return () => {
    stopped = true
    if (timer !== null) clearTimer(timer)
    socket?.close(1000)
    socket = null
  }
}
