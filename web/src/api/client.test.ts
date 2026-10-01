import { http, HttpResponse, delay } from 'msw'
import { createClient, REFRESH_LOCK } from './client'
import { ApiError } from './errors'
import { API, server } from '@/test/server'
import { tokenBody } from '@/test/fixtures'

type Timer = { fn: () => void; ms: number }

/** A client with fake timers we can fire by hand, and no cross-tab lock unless given one. */
function setup(locks: Parameters<typeof createClient>[0]['locks'] = null) {
  const timers: Timer[] = []
  const client = createClient({
    baseUrl: API,
    locks,
    setTimer: (fn, ms) => {
      const t = { fn, ms }
      timers.push(t)
      return t
    },
    clearTimer: (t) => {
      const i = timers.indexOf(t as Timer)
      if (i >= 0) timers.splice(i, 1)
    },
  })
  return { client, timers }
}

/** /auth/refresh answering new tokens tok-1, tok-2, ...; counts its calls. */
function refreshes() {
  const seen = { calls: 0, credentials: [] as RequestCredentials[] }
  server.use(
    http.post(`${API}/auth/refresh`, async ({ request }) => {
      seen.calls += 1
      seen.credentials.push(request.credentials)
      await delay(10)
      return HttpResponse.json(tokenBody(`tok-${seen.calls}`))
    }),
  )
  return seen
}

/** GET /me that accepts only `valid` as the Bearer token; records what it saw. */
function meAccepting(valid: string) {
  const auths: (string | null)[] = []
  server.use(
    http.get(`${API}/me`, ({ request }) => {
      const auth = request.headers.get('authorization')
      auths.push(auth)
      return auth === `Bearer ${valid}`
        ? HttpResponse.json({ ok: true })
        : HttpResponse.json({ detail: 'sign in first' }, { status: 401 })
    }),
  )
  return auths
}

describe('refresh', () => {
  it('restores the session on load and keeps the token in memory only', async () => {
    const seen = refreshes()
    const { client } = setup()
    expect(client.getState().status).toBe('loading')

    await client.restore()

    expect(client.getState()).toMatchObject({ status: 'signedIn', user: { email: 'taufik@hey.com' } })
    expect(client.getToken()).toBe('tok-1')
    expect(seen.credentials).toEqual(['include'])
    expect(localStorage.length).toBe(0)
  })

  it('is single-flight: concurrent calls share one request', async () => {
    const seen = refreshes()
    const { client } = setup()

    const results = await Promise.all([client.refresh(), client.refresh(), client.refresh()])

    expect(seen.calls).toBe(1)
    expect(results.map((r) => r?.access_token)).toEqual(['tok-1', 'tok-1', 'tok-1'])
    await client.refresh() // a later one is a new request
    expect(seen.calls).toBe(2)
  })

  it('takes the cross-tab lock around the request', async () => {
    refreshes()
    const names: string[] = []
    const locks = {
      request: ((name: string, cb: () => Promise<unknown>) => {
        names.push(name)
        return cb()
      }) as unknown as LockManager['request'],
    }
    const { client } = setup({ request: locks.request })

    await Promise.all([client.refresh(), client.refresh()])

    expect(names).toEqual([REFRESH_LOCK])
  })

  it('is scheduled about a minute before the token expires', async () => {
    const seen = refreshes()
    const { client, timers } = setup()

    await client.restore()
    expect(timers.map((t) => t.ms)).toEqual([(900 - 60) * 1000])

    const due = timers.splice(0, 1)[0]! // fired: gone from the list, as a real timer would be
    due.fn()
    await vi.waitFor(() => expect(client.getToken()).toBe('tok-2'))
    expect(seen.calls).toBe(2)
    expect(timers).toHaveLength(1) // the next one is scheduled
  })

  it('signs out when the gateway refuses the refresh cookie', async () => {
    server.use(http.post(`${API}/auth/refresh`, () => HttpResponse.json({ detail: 'sign in again' }, { status: 401 })))
    const { client, timers } = setup()

    await client.restore()

    expect(client.getState()).toEqual({ status: 'signedOut', user: null })
    expect(client.getToken()).toBeNull()
    expect(timers).toHaveLength(0)
  })
})

describe('requests', () => {
  it('send the Bearer token and cookies', async () => {
    refreshes()
    const auths = meAccepting('tok-1')
    const { client } = setup()
    await client.restore()

    await expect(client.request('/me')).resolves.toEqual({ ok: true })
    expect(auths).toEqual(['Bearer tok-1'])
  })

  it('on a 401, refresh once and retry once', async () => {
    const seen = refreshes()
    const { client } = setup()
    await client.restore() // tok-1, which the gateway no longer takes
    const auths = meAccepting('tok-2')

    await expect(client.request('/me')).resolves.toEqual({ ok: true })

    expect(seen.calls).toBe(2)
    expect(auths).toEqual(['Bearer tok-1', 'Bearer tok-2'])
  })

  it('concurrent 401s share one refresh', async () => {
    const seen = refreshes()
    const { client } = setup()
    await client.restore()
    meAccepting('tok-2')

    await Promise.all([client.request('/me'), client.request('/me'), client.request('/me')])

    expect(seen.calls).toBe(2) // the restore, then one for all three
  })

  it('a refresh failure signs out and rejects the request', async () => {
    refreshes()
    const { client } = setup()
    await client.restore()
    meAccepting('never')
    server.use(http.post(`${API}/auth/refresh`, () => HttpResponse.json({ detail: 'sign in again' }, { status: 401 })))

    await expect(client.request('/me')).rejects.toMatchObject({ status: 401 })
    expect(client.getState().status).toBe('signedOut')
    expect(client.getToken()).toBeNull()
  })

  it('a 401 after the retry signs out instead of looping', async () => {
    const seen = refreshes()
    const { client } = setup()
    await client.restore()
    const auths = meAccepting('never')

    await expect(client.request('/me')).rejects.toBeInstanceOf(ApiError)
    expect(seen.calls).toBe(2)
    expect(auths).toHaveLength(2)
    expect(client.getState().status).toBe('signedOut')
  })

  it('retry: false keeps a 401 as the answer (a wrong password)', async () => {
    const seen = refreshes()
    server.use(
      http.post(`${API}/auth/login`, () => HttpResponse.json({ detail: 'wrong email or password' }, { status: 401 })),
    )
    const { client } = setup()

    await expect(client.request('/auth/login', { method: 'POST', body: {}, retry: false })).rejects.toMatchObject({
      status: 401,
      message: 'wrong email or password',
    })
    expect(seen.calls).toBe(0)
  })

  it('turns errors into ApiError with the detail and the body', async () => {
    refreshes()
    server.use(
      http.post(`${API}/sessions`, () =>
        HttpResponse.json({ code: 'daily_limit', used: 50000, limit: 50000, resets_at: 'x' }, { status: 429 }),
      ),
    )
    const { client } = setup()
    await client.restore()

    const e = await client.request<never>('/sessions', { method: 'POST', body: { message: 'hi' } }).catch((e: unknown) => e as ApiError)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.dailyLimit).toEqual({ code: 'daily_limit', used: 50000, limit: 50000, resets_at: 'x' })
  })

  it('a network failure is status 0 and keeps the session', async () => {
    refreshes()
    server.use(http.get(`${API}/me`, () => HttpResponse.error()))
    const { client } = setup()
    await client.restore()

    await expect(client.request('/me')).rejects.toMatchObject({ status: 0 })
    expect(client.getState().status).toBe('signedIn')
  })
})

describe('logout', () => {
  it('posts /auth/logout with cookies and drops the token', async () => {
    refreshes()
    const calls: RequestCredentials[] = []
    server.use(
      http.post(`${API}/auth/logout`, ({ request }) => {
        calls.push(request.credentials)
        return HttpResponse.json({ ok: true })
      }),
    )
    const { client, timers } = setup()
    await client.restore()

    await client.logout()

    expect(calls).toEqual(['include'])
    expect(client.getToken()).toBeNull()
    expect(client.getState().status).toBe('signedOut')
    expect(timers).toHaveLength(0)
  })

  it('signs out here even when the gateway is unreachable', async () => {
    refreshes()
    server.use(http.post(`${API}/auth/logout`, () => HttpResponse.error()))
    const { client } = setup()
    await client.restore()

    await client.logout()

    expect(client.getState().status).toBe('signedOut')
  })
})
