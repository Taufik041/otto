import { followSession, type LiveState } from './live'
import type { SessionEvent } from './reduce'

class FakeSocket {
  static all: FakeSocket[] = []
  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  closed: number | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.all.push(this)
  }
  close(code = 1000) {
    this.closed = code
  }
  open() {
    this.onopen?.({})
  }
  send(e: unknown) {
    this.onmessage?.({ data: JSON.stringify(e) })
  }
  drop(code = 1006) {
    this.onclose?.({ code })
  }
}

const ev = (seq: number): SessionEvent => ({ seq, ts: 't', type: 'session.status', payload: { status: 'running' } })

function setup({ stored = [ev(1), ev(2)], ticketFails = 0 } = {}) {
  FakeSocket.all = []
  const got: number[] = []
  const states: LiveState[] = []
  const timers: { fn: () => void; ms: number }[] = []
  const loads: number[] = []
  let tickets = 0
  let fails = ticketFails
  const stop = followSession({
    sessionId: 's1',
    wsBase: 'ws://api',
    loadEvents: async (after) => {
      loads.push(after)
      return stored.filter((e) => e.seq > after)
    },
    ticket: async () => {
      if (fails > 0) {
        fails--
        throw new Error('offline')
      }
      return `t${++tickets}`
    },
    onEvents: (es) => {
      // the view's reducer dedupes by seq; model it here
      for (const e of es) if (!got.includes(e.seq)) got.push(e.seq)
    },
    onState: (s) => states.push(s),
    lastSeq: () => Math.max(0, ...got),
    WebSocket: FakeSocket,
    setTimer: (fn, ms) => {
      const t = { fn, ms }
      timers.push(t)
      return t
    },
    clearTimer: () => {},
  })
  const fire = () => timers.shift()!.fn()
  return { got, states, timers, loads, stop, fire }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

it('loads the stored events, then opens the socket after the last seq with a fresh ticket', async () => {
  const { got, states } = setup()
  await flush()
  expect(got).toEqual([1, 2])
  const [sock] = FakeSocket.all
  expect(sock!.url).toBe('ws://api/sessions/s1/ws?ticket=t1&after_seq=2')
  sock!.open()
  sock!.send(ev(3))
  sock!.send({ type: 'ping' })
  sock!.send(ev(3)) // a duplicate
  expect(got).toEqual([1, 2, 3])
  expect(states).toEqual(['connecting', 'live'])
})

it('reconnects with backoff and a new ticket after a drop, resuming after the last seq', async () => {
  const { got, states, timers, fire, loads } = setup()
  await flush()
  FakeSocket.all[0]!.open()
  FakeSocket.all[0]!.send(ev(3))
  FakeSocket.all[0]!.drop()
  expect(states.at(-1)).toBe('reconnecting')
  expect(timers.map((t) => t.ms)).toEqual([1000])

  fire()
  await flush()
  expect(loads).toEqual([0, 3])
  expect(FakeSocket.all[1]!.url).toBe('ws://api/sessions/s1/ws?ticket=t2&after_seq=3')
  FakeSocket.all[1]!.open()
  expect(states.at(-1)).toBe('live')
  expect(got).toEqual([1, 2, 3])
})

it('backs off longer while it keeps failing, and resets once connected', async () => {
  const { timers, fire } = setup({ ticketFails: 3 })
  await flush()
  expect(timers.map((t) => t.ms)).toEqual([1000])
  fire()
  await flush()
  fire()
  await flush()
  expect(FakeSocket.all).toHaveLength(0)
  fire()
  await flush()
  expect(FakeSocket.all).toHaveLength(1)
  FakeSocket.all[0]!.open()
  FakeSocket.all[0]!.drop()
  expect(timers.map((t) => t.ms)).toEqual([1000])
})

it('a deleted session (4404) stops for good', async () => {
  const { states, timers } = setup()
  await flush()
  FakeSocket.all[0]!.drop(4404)
  expect(states.at(-1)).toBe('closed')
  expect(timers).toEqual([])
})

it('stopping closes the socket and reconnects no more', async () => {
  const { stop, timers } = setup()
  await flush()
  const sock = FakeSocket.all[0]!
  stop()
  expect(sock.closed).toBe(1000)
  sock.drop()
  expect(timers).toEqual([])
})
