import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { API, server } from '@/test/server'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { Landing, LandingNotFound } from './Landing'
import { landingQueryClient, LOOP_MS, T } from './replay'
import { Replay } from './Replay'

function page(ui: ReactElement) {
  const qc = landingQueryClient() // as main.tsx does: an unexpected request fails the test (MSW)
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

/** An IntersectionObserver the test moves: `show(false)` scrolls the hero away. */
function observer() {
  const real = globalThis.IntersectionObserver
  let notify: (on: boolean) => void = () => {}
  globalThis.IntersectionObserver = class {
    constructor(cb: IntersectionObserverCallback) {
      notify = (on) => cb([{ isIntersecting: on } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
    }
    observe() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver
  return { show: (on: boolean) => act(() => notify(on)), restore: () => (globalThis.IntersectionObserver = real) }
}

function tabHidden(hidden: boolean) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') })
  act(() => void document.dispatchEvent(new Event('visibilitychange')))
}

describe('the replay', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] }))
  afterEach(() => vi.useRealTimers())
  const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
  const hero = () => screen.getByRole('img', { name: /A replay of Otto at work/ })
  /** plays to `t` ms into the loop, from `from`: a render a tick (200ms), as a browser would */
  const playTo = async (t: number, from: number) => {
    for (let left = t - from + 100; left > 0; left -= 200) await tick(Math.min(200, left))
  }

  it('plays the issue in the real app components: picker, card, PR, CI, Fix CI; then loops', async () => {
    page(<Replay width={1112} />)
    const r = within(hero())
    expect(r.getByText('What should we build today?')).toBeInTheDocument()
    expect(r.getByText('Message Otto. Type @ to mention a repo.')).toBeInTheDocument()

    await playTo(T.hash, 0)
    expect(r.getByText('Open issues in acme/shop')).toBeInTheDocument()
    expect(r.getAllByRole('option')).toHaveLength(3)

    await playTo(T.move, T.hash)
    expect(r.getAllByRole('option')).toHaveLength(2)
    expect(r.getByRole('option', { selected: true })).toHaveTextContent('#12Bulk discount not applied at exactly 10 units')

    await playTo(T.pick, T.move)
    expect(r.queryByRole('listbox')).not.toBeInTheDocument()
    expect(r.getByRole('button', { name: 'Remove issue #12' })).toBeInTheDocument()

    await playTo(T.send, T.pick)
    const card = r.getByRole('region', { name: 'Issue #12' })
    expect(within(card).getByText('Open')).toBeInTheDocument()
    expect(within(card).getByText('bug')).toBeInTheDocument()

    await playTo(T.proposed, T.send)
    expect(r.getByRole('link', { name: 'Closes #12' })).toBeInTheDocument()
    expect(r.getAllByText('9 tests passed').length).toBeGreaterThan(0)

    await playTo(T.click, T.proposed)
    expect(r.getByText('Creating pull request…')).toBeInTheDocument()
    expect(hero().querySelector('[data-cursor]')).not.toBeNull()

    await playTo(T.opened, T.click)
    expect(r.getByRole('region', { name: 'Pull request opened' })).toHaveTextContent('Open')

    await playTo(T.ciWaiting, T.opened)
    expect(r.getByText('Waiting for CI')).toBeInTheDocument()
    await playTo(T.ciRunning, T.ciWaiting)
    expect(r.getByText('CI running · 2 checks')).toBeInTheDocument()
    await playTo(T.ciFailed, T.ciRunning)
    expect(r.getAllByText('CI failed · tests').length).toBeGreaterThan(0)
    expect(r.getByRole('button', { name: 'Fix CI' })).toBeEnabled()

    await playTo(T.fixClick, T.ciFailed)
    expect(r.getByRole('button', { name: 'Fixing CI…' })).toBeInTheDocument()

    await playTo(T.fixing, T.fixClick)
    expect(r.getByText('Fix CI: tests')).toBeInTheDocument()

    await playTo(T.ciPassed, T.fixing)
    const updated = r.getByRole('region', { name: 'Pull request updated' })
    expect(within(updated).getByText('CI passed')).toBeInTheDocument()
    expect(within(updated).getByRole('link', { name: 'Closes #12' })).toBeInTheDocument()

    await playTo(LOOP_MS, T.ciPassed) // the next loop starts over
    expect(r.queryByText('CI passed')).not.toBeInTheDocument()
    expect(r.getByText('What should we build today?')).toBeInTheDocument()
  }, 30_000) // ~250 renders

  it('reduced motion: one still frame, the PR with CI passed and Closes #12', async () => {
    const restore = media('prefers-reduced-motion')
    const intervals = vi.spyOn(globalThis, 'setInterval')
    try {
      page(<Replay width={1112} />)
      const r = within(hero())
      const updated = r.getByRole('region', { name: 'Pull request updated' })
      expect(within(updated).getByText('CI passed')).toBeInTheDocument()
      expect(within(updated).getByRole('link', { name: 'Closes #12' })).toBeInTheDocument()
      expect(hero().querySelector('[data-cursor]')).toBeNull()
      await tick(LOOP_MS)
      expect(within(updated).getByText('CI passed')).toBeInTheDocument() // nothing moved
      expect(intervals).not.toHaveBeenCalled() // no clock: nothing plays
    } finally {
      restore()
    }
  })

  it('pauses off screen and in a hidden tab, and resumes where it left off', async () => {
    const io = observer()
    try {
      page(<Replay width={1112} />)
      const r = within(hero())
      await playTo(T.hash, 0)
      expect(r.getAllByRole('option')).toHaveLength(3)

      await io.show(false) // scrolled away: it holds
      await tick(30_000)
      expect(r.getAllByRole('option')).toHaveLength(3)
      expect(r.queryByRole('region', { name: 'Issue #12' })).not.toBeInTheDocument()
      await io.show(true)
      await playTo(T.move, T.hash)
      expect(r.getAllByRole('option')).toHaveLength(2) // from where it was, not 30s on

      tabHidden(true) // another tab: it holds
      await tick(30_000)
      expect(r.getAllByRole('option')).toHaveLength(2)
      tabHidden(false)
      await playTo(T.send, T.move)
      expect(r.getByRole('region', { name: 'Issue #12' })).toBeInTheDocument()
    } finally {
      io.restore()
      tabHidden(false)
    }
  })

  it('makes no network request, all the way round', async () => {
    const requests: string[] = []
    const log = ({ request }: { request: Request }) => void requests.push(request.url)
    server.events.on('request:start', log)
    const fetches = vi.spyOn(globalThis, 'fetch')
    try {
      page(<Replay width={1112} />)
      await playTo(T.fixing, 0) // both pretend clicks included
      expect(screen.getByText('Fix CI: tests')).toBeInTheDocument()
      await playTo(LOOP_MS, T.fixing)
      expect(screen.getByText('What should we build today?')).toBeInTheDocument() // it went round
      expect(requests).toEqual([])
      expect(fetches).not.toHaveBeenCalled()
    } finally {
      server.events.removeListener('request:start', log)
      fetches.mockRestore()
    }
  }, 30_000)
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
