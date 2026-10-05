import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { api, WS_URL } from '@/api'
import { keys } from '@/api/queries'
import type { SessionDetail, SessionSummary } from '@/api/types'
import { followSession, type LiveState } from './live'
import { emptyState, reduce, view, type SessionEvent, type View } from './reduce'

const SEEN_DEBOUNCE = 400 // ms: a burst of events posts /seen once
const ACTIVE = new Set(['provisioning', 'queued', 'running'])
const visible = () => document.visibilityState === 'visible'

/**
 * A session's view, kept live over the WebSocket.
 *
 * While the chat is open and the tab visible, what arrives is seen: POST /sessions/{id}/seen with
 * the latest seq (debounced), so a chat you're watching never wants attention in the sidebar. Its
 * row there is cleared at once, and the list is refetched only after the seen post, so it never
 * shows "done" meanwhile. In a hidden tab the list refreshes as usual; seen waits for visibility.
 */
export function useSessionView(id: string): { view: View; connection: LiveState } {
  const [state, dispatch] = useReducer(
    (s: ReturnType<typeof emptyState>, events: SessionEvent[] | 'reset') => (events === 'reset' ? emptyState() : reduce(s, events)),
    undefined,
    emptyState,
  )
  const [connection, setConnection] = useState<LiveState>('connecting')
  const lastSeq = useRef(0)
  const qc = useQueryClient()
  lastSeq.current = Math.max(0, ...state.seen)

  useEffect(() => {
    dispatch('reset')
    lastSeq.current = 0
    let posted = 0
    let timer: ReturnType<typeof setTimeout> | null = null
    let refreshAfter = false // refetch the list once the seen post lands
    const refreshList = () => void qc.invalidateQueries({ queryKey: keys.sessions, exact: true })

    const markSeen = () => {
      if (!visible()) return
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        const seq = lastSeq.current
        const refresh = refreshAfter
        refreshAfter = false
        if (seq <= posted) return void (refresh && refreshList())
        posted = seq
        api.seen(id, seq).then(() => refresh && refreshList(), () => refresh && refreshList())
      }, SEEN_DEBOUNCE)
    }
    const onVisible = () => visible() && markSeen()
    document.addEventListener('visibilitychange', onVisible)

    const stop = followSession({
      sessionId: id,
      wsBase: WS_URL,
      loadEvents: (after) => api.events(id, after),
      ticket: async () => (await api.wsTicket(id)).ticket,
      onEvents: (events) => {
        if (!events.length) return
        dispatch(events)
        lastSeq.current = Math.max(lastSeq.current, ...events.map((e) => e.seq))
        // the chat's title lives on the session (GET /sessions/{id}): an auto title updates it there,
        // so a later rename (which refetches it) still wins
        const titled = events.filter((e) => e.type === 'session.titled').at(-1)
        const title = typeof titled?.payload.title === 'string' ? titled.payload.title : null
        // a model found unusable: the picker's list says so now (GET /models)
        if (events.some((e) => e.type === 'error' && e.payload.stage === 'model')) void qc.invalidateQueries({ queryKey: keys.models })
        if (title) qc.setQueryData<SessionDetail>(keys.session(id), (d) => (d ? { ...d, title } : d))
        const listChanged = events.some((e) => e.type === 'session.status' || e.type === 'pr.opened' || e.type === 'session.titled')
        if (!visible()) {
          if (listChanged) refreshList() // not watching: the sidebar should show the dot
          return
        }
        // watching: this chat wants no attention; working while Otto works, else nothing
        const status = events.filter((e) => e.type === 'session.status').at(-1)?.payload.status
        qc.setQueryData<SessionSummary[]>(keys.sessions, (list) =>
          list?.map((s) =>
            s.id !== id
              ? s
              : { ...s, attention: typeof status === 'string' ? (ACTIVE.has(status) ? 'working' : null) : s.attention === 'working' ? 'working' : null },
          ),
        )
        refreshAfter ||= listChanged
        markSeen()
      },
      onState: setConnection,
      lastSeq: () => lastSeq.current,
    })
    return () => {
      stop()
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [id, qc])

  const v = useMemo(() => view(state), [state])
  return { view: v, connection }
}
