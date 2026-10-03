import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { api, WS_URL } from '@/api'
import { keys } from '@/api/queries'
import type { SessionDetail } from '@/api/types'
import { followSession, type LiveState } from './live'
import { emptyState, reduce, view, type SessionEvent, type View } from './reduce'

/** A session's view, kept live over the WebSocket. Final statuses refresh the sidebar's list. */
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
    return followSession({
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
        if (events.some((e) => e.type === 'session.status' || e.type === 'pr.opened' || e.type === 'session.titled')) {
          void qc.invalidateQueries({ queryKey: keys.sessions, exact: true }) // the sidebar's list
        }
      },
      onState: setConnection,
      lastSeq: () => lastSeq.current,
    })
  }, [id, qc])

  const v = useMemo(() => view(state), [state])
  return { view: v, connection }
}
