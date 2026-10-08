import { act, renderHook } from '@testing-library/react'
import { checkHealth, parseOverride, REFRESH_MS, TIMEOUT_MS, useStatus } from './status'

const API = 'https://api.example.dev'
const answer = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const up = () => answer({ status: 'up', workers: 'online', version: 'x' })

describe('checkHealth: live only when Otto is up and its workers answer', () => {
  it('asks GET /health, without credentials', async () => {
    const f = up()
    expect(await checkHealth(API, f)).toBe('live')
    expect(f).toHaveBeenCalledWith(`${API}/health`, expect.objectContaining({ credentials: 'omit' }))
  })

  it('up with its workers offline is "chat only"', async () => {
    expect(await checkHealth(API, answer({ status: 'up', workers: 'offline', version: 'x' }))).toBe('chat')
  })

  it.each([
    ['signups paused', answer({ status: 'paused', workers: 'online', version: 'x' })],
    ['a 502 from the tunnel', answer({ error: 'bad gateway' }, 502)],
    ['not JSON', vi.fn(async () => new Response('<html>', { status: 200 }))],
    ['unreachable', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch')))],
  ])('%s is offline', async (_, f) => {
    expect(await checkHealth(API, f)).toBe('offline')
  })

  it('no answer within 2 seconds is offline', async () => {
    vi.useFakeTimers()
    try {
      const f = vi.fn((_url: string, init?: RequestInit) =>
        new Promise<Response>((_, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))),
      )
      const result = checkHealth(API, f)
      expect(TIMEOUT_MS).toBe(2_000)
      await vi.advanceTimersByTimeAsync(TIMEOUT_MS)
      expect(await result).toBe('offline')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('VITE_STATUS_OVERRIDE', () => {
  it.each([
    [undefined, 'auto'], ['', 'auto'], ['auto', 'auto'], ['up', 'up'], ['UP', 'up'], ['down', 'down'], ['nonsense', 'auto'],
  ] as const)('%s → %s', (value, expected) => {
    expect(parseOverride(value)).toBe(expected)
  })

  it('up and down never ask the gateway', async () => {
    const f = up()
    const { result: a } = renderHook(() => useStatus({ apiUrl: API, override: 'down', fetch: f }))
    const { result: b } = renderHook(() => useStatus({ apiUrl: API, override: 'up', fetch: f }))
    expect(a.current).toBe('offline')
    expect(b.current).toBe('live')
    expect(f).not.toHaveBeenCalled()
  })
})

describe('useStatus', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('checking at first, then the answer; asked again every 60 seconds', async () => {
    let live = true
    const f = vi.fn(async () =>
      new Response(JSON.stringify({ status: 'up', workers: live ? 'online' : 'offline', version: 'x' }), { status: 200 }),
    )
    const { result } = renderHook(() => useStatus({ apiUrl: API, override: 'auto', fetch: f }))
    expect(result.current).toBe('checking')
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(result.current).toBe('live')
    expect(f).toHaveBeenCalledTimes(1)

    live = false
    await act(() => vi.advanceTimersByTimeAsync(REFRESH_MS - 1))
    expect(f).toHaveBeenCalledTimes(1)
    await act(() => vi.advanceTimersByTimeAsync(1))
    expect(f).toHaveBeenCalledTimes(2)
    expect(result.current).toBe('chat')
    expect(REFRESH_MS).toBe(60_000)
  })

  it('stops asking once the page is gone', async () => {
    const f = up()
    const { unmount } = renderHook(() => useStatus({ apiUrl: API, override: 'auto', fetch: f }))
    await act(() => vi.advanceTimersByTimeAsync(0))
    unmount()
    await vi.advanceTimersByTimeAsync(5 * REFRESH_MS)
    expect(f).toHaveBeenCalledTimes(1)
  })
})
