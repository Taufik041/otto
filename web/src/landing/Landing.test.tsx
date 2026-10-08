import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { API, server } from '@/test/server'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { Landing, LandingNotFound } from './Landing'
import { CLICK_AT, LOOP_MS, OPENED_AT, seedCatalog } from './replay'
import { Replay } from './Replay'

function page(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  seedCatalog(qc) // as main.tsx does: an unexpected request fails the test (MSW)
  return render(
    <ThemeProvider fixed="system">
      <QueryClientProvider client={qc}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}

/** matchMedia answering true for the queries given (phones, reduced motion) */
function media(...on: string[]) {
  const real = window.matchMedia
  window.matchMedia = ((q: string) => ({ ...real(q), matches: on.some((o) => q.includes(o)) })) as typeof window.matchMedia
  return () => (window.matchMedia = real)
}

const workers = (w: 'online' | 'offline') =>
  server.use(http.get(`${API}/health`, () => HttpResponse.json({ status: 'up', workers: w, version: 't' })))

describe('the replay', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] }))
  afterEach(() => vi.useRealTimers())
  const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

  it('plays the session in the real app components, clicks Create, and loops', async () => {
    page(<Replay width={1112} />)
    const replay = screen.getByRole('img', { name: /A replay of Otto at work/ })
    expect(within(replay).getByText(/two tests are failing/)).toBeInTheDocument()

    await tick(5_000)
    expect(within(replay).getAllByText('2 failed, 7 passed').length).toBeGreaterThan(0)

    await tick(CLICK_AT - 5_000 + 200)
    expect(within(replay).getByText('Creating pull request…')).toBeInTheDocument()
    expect(replay.querySelector('[data-cursor]')).not.toBeNull()

    await tick(OPENED_AT - CLICK_AT)
    expect(within(replay).getByText('Pull request opened')).toBeInTheDocument()
    expect(within(replay).getByText('#9')).toBeInTheDocument()

    await tick(LOOP_MS - OPENED_AT + 500) // the next loop starts over
    expect(within(replay).queryByText('Pull request opened')).not.toBeInTheDocument()
    expect(within(replay).getByText(/two tests are failing/)).toBeInTheDocument()
  })

  it('reduced motion: the final state, still', async () => {
    const restore = media('prefers-reduced-motion')
    const intervals = vi.spyOn(globalThis, 'setInterval')
    try {
      page(<Replay width={1112} />)
      const replay = screen.getByRole('img', { name: /A replay of Otto at work/ })
      expect(within(replay).getByText('Pull request opened')).toBeInTheDocument()
      expect(replay.querySelector('[data-cursor]')).toBeNull()
      await tick(LOOP_MS)
      expect(within(replay).getByText('Pull request opened')).toBeInTheDocument() // nothing moved
      expect(intervals).not.toHaveBeenCalled() // no clock: nothing plays
    } finally {
      restore()
    }
  })
})

describe('the status pill and the way in', () => {
  it('live: "Live", and Get started and Log in go to the app\'s sign-in', async () => {
    workers('online')
    page(<Landing />)
    expect(await screen.findByText('Live')).toBeInTheDocument()
    for (const name of ['Get started', 'Log in'])
      for (const link of screen.getAllByRole('link', { name })) expect(link).toHaveAttribute('href', 'https://ottoci.taufi.dev/login')
    await userEvent.click(screen.getAllByRole('link', { name: 'Get started' })[0]!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('offline: "Offline", and Get started opens the offline dialog instead', async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.error()))
    page(<Landing />)
    expect(await screen.findByText('Offline')).toBeInTheDocument()
    expect(screen.getByText('Offline right now')).toBeInTheDocument() // the footer's line
    await userEvent.click(screen.getAllByRole('link', { name: 'Get started' })[0]!)
    const d = screen.getByRole('dialog', { name: 'Otto is offline right now.' })
    expect(within(d).getByText(/a free beta that runs on Taufik's own hardware/)).toBeInTheDocument()
    expect(within(d).getByRole('link', { name: 'Watch the demo' })).toHaveAttribute('href', '#demo')
    await userEvent.click(within(d).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Log in' }))
    expect(screen.getByRole('dialog', { name: 'Otto is offline right now.' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('the sections, the legal links and the code', async () => {
    workers('online')
    page(<Landing />)
    for (const h of ['Three steps.', 'Small fixes, done properly.', 'Built like real infrastructure.', 'Stop babysitting small fixes.'])
      expect(screen.getByText(h)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Read the code on GitHub' })).toHaveAttribute('href', 'https://github.com/Taufik041/otto')
    expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', 'https://ottoci.taufi.dev/legal/privacy')
    expect(screen.getByRole('link', { name: 'hello@taufi.dev' })).toHaveAttribute('href', 'mailto:hello@taufi.dev')
    expect(screen.getByText('Built by Taufik Khan')).toBeInTheDocument()
    expect(screen.getByText('Otto is in beta. It may be offline at times.')).toBeInTheDocument()
    expect(screen.getByText('Free during beta')).toBeInTheDocument()
    expect(within(screen.getByRole('banner')).getByText('Beta')).toBeInTheDocument() // the nav's pill
    expect(screen.queryByRole('link', { name: 'LinkedIn' })).not.toBeInTheDocument() // VITE_LINKEDIN_URL unset
  })
})

describe('three states', () => {
  it('chat only: amber "Chat only", the footer says so, and Get started still goes to the app', async () => {
    workers('offline')
    page(<Landing />)
    expect(await screen.findByText('Chat only')).toBeInTheDocument()
    expect(screen.getAllByText('Chat is live · sandboxes are offline right now').length).toBeGreaterThan(0)
    await userEvent.click(screen.getAllByRole('link', { name: 'Get started' })[0]!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('paused or unreachable: "Offline", and only then the dialog', async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.json({ status: 'paused', workers: 'online', version: 't' })))
    page(<Landing />)
    expect(await screen.findByText('Offline')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('link', { name: 'Get started' })[0]!)
    expect(screen.getByRole('dialog', { name: 'Otto is offline right now.' })).toBeInTheDocument()
  })
})

describe('phones', () => {
  it('the menu: a full-screen sheet with the links, the status and the buttons at the bottom', async () => {
    const restore = media('max-width')
    try {
      workers('online')
      page(<Landing />)
      await screen.findByText('Otto is live') // the pill's label, for screen readers
      await userEvent.click(screen.getByRole('button', { name: 'Menu' }))
      const sheet = screen.getByRole('dialog', { name: 'Menu' })
      expect(within(sheet).getByRole('link', { name: 'How it works' })).toHaveAttribute('href', '/#how')
      expect(within(sheet).getByRole('link', { name: 'Architecture' })).toHaveAttribute('href', '/#architecture')
      expect(within(sheet).getByRole('link', { name: 'Get started' })).toBeInTheDocument()
      expect(within(sheet).getAllByText('Otto is live').length).toBeGreaterThan(0)
      await userEvent.click(screen.getByRole('button', { name: 'Close menu' }))
      expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()
    } finally {
      restore()
    }
  })
})

describe('its own 404', () => {
  it('the mark, the line, and Go home', async () => {
    page(<LandingNotFound />)
    expect(screen.getByRole('heading', { name: 'This page took a wrong turn.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go home' })).toHaveAttribute('href', '/')
  })
})
