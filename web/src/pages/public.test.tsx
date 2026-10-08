import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import App from '@/App'
import { client } from '@/api'
import { renderSignedIn, Where } from '@/test/render'
import { API, server } from '@/test/server'
import { BUILD_DATE } from '@/utils/links'
import { LEGAL_DOCS, longDate } from './legal/content'
import { SettingsLayout } from './settings/SettingsLayout'

function app(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  server.use(
    http.post(`${API}/auth/logout`, () => HttpResponse.json({ ok: true })),
    http.post(`${API}/auth/refresh`, () => HttpResponse.json({ detail: 'sign in again' }, { status: 401 })),
  )
  await client.logout() // signed out: these pages are public
})

describe('the legal pages', () => {
  it.each(LEGAL_DOCS.map((d) => [d.slug, d.title] as const))('/legal/%s is public, titled %s', async (slug, title) => {
    app(`/legal/${slug}`)
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent(`/legal/${slug}`)
    expect(screen.getByText(`Last updated ${longDate(BUILD_DATE)} · Operated by Taufik Khan`)).toBeInTheDocument()
    const article = screen.getByRole('article')
    expect(article).toHaveTextContent('otto.taufi.dev')
    expect(article).toHaveTextContent('ottoci.taufi.dev')
    expect(within(article).getAllByRole('link', { name: 'hello@taufi.dev' })[0]).toHaveAttribute('href', 'mailto:hello@taufi.dev')
  })

  it('the terms: a non-commercial demo, no warranty, may be discontinued, the law of India', async () => {
    app('/legal/terms')
    const text = (await screen.findByRole('article')).textContent!
    for (const phrase of ['non-commercial', 'without warranties', 'may be discontinued', 'laws of India', 'Daily usage limits',
      'Review every pull request before you merge it', 'AI output may be wrong'])
      expect(text).toContain(phrase)
  })

  it('the privacy policy covers what the spec lists', async () => {
    app('/legal/privacy')
    const text = (await screen.findByRole('article')).textContent!
    for (const phrase of ['What we collect', 'event log', 'Security logs', 'AI providers', 'OpenRouter', 'OpenAI', 'GitHub access',
      'only when you approve', 'Vercel', 'AWS', 'Cloudflare', 'deactivates it immediately', 'within 30 days', 'never sell',
      'only essential cookies', 'Your choices'])
      expect(text).toContain(phrase)
  })

  it('acceptable use: no malware, attacks, sandbox abuse, illegal use, limit dodging, other people\'s repos', async () => {
    app('/legal/acceptable-use')
    const text = (await screen.findByRole('article')).textContent!
    for (const phrase of ['malware', 'scan', 'mining', 'proxies', 'spam', 'illegal', 'daily limits', 'without their permission'])
      expect(text).toContain(phrase)
  })

  it('a table of contents and the three documents as tabs', async () => {
    app('/legal/privacy')
    const toc = await screen.findByRole('navigation', { name: 'On this page' })
    expect(within(toc).getByRole('link', { name: 'What we collect' })).toHaveAttribute('href', '#collect')
    const docs = screen.getByRole('navigation', { name: 'Legal documents' })
    expect(within(docs).getByRole('link', { name: 'Privacy' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(within(docs).getByRole('link', { name: 'Terms' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Terms of Service' })).toBeInTheDocument()
  })

  it('an unknown document is the 404', async () => {
    app('/legal/cookies')
    expect(await screen.findByRole('heading', { name: 'This page took a wrong turn.' })).toBeInTheDocument()
  })
})

describe('the 404', () => {
  it('any unknown path, signed out or in: the mark, the line, and Go home', async () => {
    app('/nope/nothing')
    expect(await screen.findByRole('heading', { name: 'This page took a wrong turn.' })).toBeInTheDocument()
    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go home' })).toHaveAttribute('href', '/')
  })
})

describe('/request-access', () => {
  it('the invite-only form as a page; sending it says "Request sent"', async () => {
    const posted: unknown[] = []
    server.use(
      http.post(`${API}/access-requests`, async ({ request }) => {
        posted.push(await request.json())
        return HttpResponse.json({ ok: true }, { status: 201 })
      }),
    )
    app('/request-access')
    const card = await screen.findByRole('dialog', { name: 'Otto is invite-only right now.' })
    expect(within(card).queryByRole('link', { name: 'Close' })).not.toBeInTheDocument() // a page, not a dialog over one
    expect(within(card).getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    await userEvent.type(screen.getByLabelText('GitHub username or email'), 'Taufik041')
    await userEvent.click(screen.getByRole('button', { name: 'Request access' }))
    expect(await screen.findByRole('dialog', { name: 'Request sent' })).toBeInTheDocument()
    expect(posted).toEqual([{ github_login: 'Taufik041', note: '' }])
    expect(screen.getByRole('link', { name: 'Back to Otto' })).toHaveAttribute('href', 'https://otto.taufi.dev')
  })

  it('an empty form says what\'s missing', async () => {
    app('/request-access')
    await userEvent.click(await screen.findByRole('button', { name: 'Request access' }))
    expect(screen.getByText('Enter your GitHub username or email.')).toBeInTheDocument()
  })
})

describe('/auth/callback', () => {
  it.each([
    ['invite_only', 'Otto is invite-only right now.'],
    ['paused', 'Otto is offline right now.'],
  ])('a GitHub sign-up refused as %s opens the dialog in that state', async (error, title) => {
    app(`/auth/callback?error=${error}`)
    expect(await screen.findByRole('dialog', { name: title })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent(`/login?error=${error}`)
  })
})

describe('Settings links the legal pages', () => {
  it('in the sidebar', async () => {
    server.use(http.get(`${API}/github`, () => HttpResponse.json({ connected: false, login: null, avatar_url: null, installations: [] })))
    renderSignedIn(<Routes><Route path="/settings/:section?" element={<SettingsLayout />} /></Routes>, { path: '/settings/appearance' })
    const legal = await screen.findByRole('navigation', { name: 'Legal' })
    expect(within(legal).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/legal/terms')
    expect(within(legal).getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/legal/privacy')
    expect(within(legal).getByRole('link', { name: 'Acceptable use' })).toHaveAttribute('href', '/legal/acceptable-use')
  })
})
