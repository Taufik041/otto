import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Navigate, Route, Routes } from 'react-router'
import { client } from '@/api'
import { GuestOnly, RequireAuth } from '@/auth/guards'
import { Where } from '@/test/render'
import { API, server } from '@/test/server'
import { tokenBody } from '@/test/fixtures'
import { LoginPage } from './LoginPage'

function app(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="/signup" element={<Navigate to="/login" replace />} />
          <Route path="/welcome" element={<p>onboarding</p>} />
          <Route path="/legal/:doc" element={<p>legal</p>} />
          <Route path="*" element={<RequireAuth><p>the app</p></RequireAuth>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The gateway's auth routes; `exists` answers /auth/email-status. Returns what was posted. */
function gateway({
  exists = true,
  login = () => HttpResponse.json(tokenBody()),
  signup = () => HttpResponse.json(tokenBody(), { status: 201 }),
  status,
}: {
  exists?: boolean
  login?: () => Response
  signup?: () => Response
  status?: () => Response
} = {}) {
  const posted: { path: string; body: unknown }[] = []
  const log = (path: string, res: () => Response) =>
    http.post(`${API}${path}`, async ({ request }) => {
      posted.push({ path, body: await request.json() })
      return res()
    })
  server.use(
    log('/auth/email-status', status ?? (() => HttpResponse.json({ exists }))),
    log('/auth/login', login),
    log('/auth/signup', signup),
    log('/auth/forgot', () => HttpResponse.json({ ok: true })),
    log('/access-requests', () => HttpResponse.json({ ok: true }, { status: 201 })),
  )
  return posted
}

const dialog = () => screen.getByRole('dialog')
const email = () => screen.getByLabelText('Email address')
async function enterEmail(value = 'taufik@hey.com') {
  await userEvent.type(email(), value)
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
}

beforeEach(async () => {
  server.use(http.post(`${API}/auth/logout`, () => HttpResponse.json({ ok: true })))
  await client.logout() // signed out
})

describe('the first step', () => {
  it('is "Log in or sign up": GitHub, an email, Continue, and the terms', async () => {
    app('/login')
    const d = await screen.findByRole('dialog', { name: 'Log in or sign up' })
    expect(within(d).getByText('Describe a change. Otto opens the pull request.')).toBeInTheDocument()
    expect(within(d).getByRole('button', { name: 'Continue with GitHub' })).toBeInTheDocument()
    expect(within(d).queryByRole('button', { name: 'Continue with Google' })).not.toBeInTheDocument() // VITE_GOOGLE_AUTH is off
    expect(within(d).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/legal/terms')
    expect(within(d).getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/legal/privacy')
  })

  it('a bad email is an inline error, and nothing is asked', async () => {
    const posted = gateway()
    app('/login')
    await enterEmail('taufik@hey')
    expect(await within(dialog()).findByText('Enter a valid email.')).toBeInTheDocument()
    expect(email()).toHaveAttribute('aria-invalid', 'true')
    expect(posted).toEqual([])
  })

  it('/signup lands here too', async () => {
    app('/signup')
    expect(await screen.findByRole('dialog', { name: 'Log in or sign up' })).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/login')
  })

  it('a cancelled GitHub sign-in says so', async () => {
    app('/?github_error=access_denied')
    expect(await screen.findByText('GitHub sign-in was cancelled. Try again, or use your email.')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/login?github_error=access_denied')
  })

  it('a signed-out visit remembers where it was going', async () => {
    app('/settings/usage')
    expect(screen.getByTestId('where')).toHaveTextContent('/login?next=%2Fsettings%2Fusage')
  })
})

describe('an existing account', () => {
  it('"Welcome back": a wrong password is an inline error; the right one goes to ?next', async () => {
    let ok = false
    const posted = gateway({
      login: () => (ok ? HttpResponse.json(tokenBody()) : HttpResponse.json({ detail: 'wrong email or password' }, { status: 401 })),
    })
    app('/login?next=%2Fsettings%2Fusage')
    await enterEmail(' Taufik@Hey.com ')
    expect(await screen.findByRole('dialog', { name: 'Welcome back' })).toBeInTheDocument()
    expect(within(dialog()).getByText('Taufik@Hey.com')).toBeInTheDocument()
    expect(posted[0]).toEqual({ path: '/auth/email-status', body: { email: 'Taufik@Hey.com' } })

    await userEvent.type(screen.getByLabelText('Password'), 'nope{Enter}')
    expect(await screen.findByText("That password isn't right. Try again or reset it.")).toBeInTheDocument()

    ok = true
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/settings/usage')
  })

  it('Edit goes back to the email', async () => {
    gateway()
    app('/login')
    await enterEmail()
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Edit' }))
    expect(screen.getByRole('dialog', { name: 'Log in or sign up' })).toBeInTheDocument()
    expect(email()).toHaveValue('taufik@hey.com')
  })

  it('Forgot password? sends the link, then "Check your inbox" (it expires in 1 hour)', async () => {
    const posted = gateway()
    app('/login')
    await enterEmail()
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Forgot password?' }))
    expect(await screen.findByRole('dialog', { name: 'Check your inbox' })).toBeInTheDocument()
    expect(within(dialog()).getByText('We sent a reset link to taufik@hey.com. It expires in 1 hour.')).toBeInTheDocument()
    expect(posted.at(-1)).toEqual({ path: '/auth/forgot', body: { email: 'taufik@hey.com' } })

    await userEvent.click(within(dialog()).getByRole('button', { name: 'Back to log in' }))
    expect(screen.getByRole('dialog', { name: 'Welcome back' })).toBeInTheDocument()
  })
})

describe('when email isn\'t set up (GET /health: password_reset false)', () => {
  it('"Forgot password?" is hidden', async () => {
    server.use(
      http.get(`${API}/health`, () =>
        HttpResponse.json({ status: 'up', workers: 'online', version: 't', password_reset: false }),
      ),
    )
    gateway()
    app('/login')
    await enterEmail()
    expect(await screen.findByRole('dialog', { name: 'Welcome back' })).toBeInTheDocument()
    await waitFor(() => expect(within(dialog()).queryByRole('button', { name: 'Forgot password?' })).not.toBeInTheDocument())
  })
})

describe('the beta pill', () => {
  it('sits beside the mark', async () => {
    app('/login')
    const d = await screen.findByRole('dialog', { name: 'Log in or sign up' })
    expect(within(d).getByText('Beta')).toBeInTheDocument()
  })
})

describe('a new account', () => {
  it('"Create your account": name and password, with the real rule (8 characters)', async () => {
    const posted = gateway({ exists: false })
    app('/login')
    await enterEmail('new@example.com')
    expect(await screen.findByRole('dialog', { name: 'Create your account' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Your name'), 'New Person')
    await userEvent.type(screen.getByLabelText('Password'), 'short')
    expect(within(dialog()).getByText('Use at least 8 characters.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(posted.map((p) => p.path)).toEqual(['/auth/email-status']) // not sent

    await userEvent.type(screen.getByLabelText('Password'), 'enough')
    expect(within(dialog()).queryByText('Use at least 8 characters.')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/welcome'))
    expect(posted.at(-1)).toEqual({ path: '/auth/signup', body: { name: 'New Person', email: 'new@example.com', password: 'shortenough' } })
  })

  it('a name is required', async () => {
    const posted = gateway({ exists: false })
    app('/login')
    await enterEmail('new@example.com')
    await userEvent.type(await screen.findByLabelText('Password'), 'long enough pw')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(within(dialog()).getByText('Enter your name.')).toBeInTheDocument()
    expect(posted.map((p) => p.path)).toEqual(['/auth/email-status'])
  })

  it('invite-only: the request-access form, prefilled; sending it shows "Request sent"', async () => {
    const posted = gateway({
      exists: false,
      signup: () => HttpResponse.json({ error: 'invite_only', detail: 'Otto is invite-only right now.' }, { status: 403 }),
    })
    app('/login')
    await enterEmail('new@example.com')
    await userEvent.type(await screen.findByLabelText('Your name'), 'New Person')
    await userEvent.type(screen.getByLabelText('Password'), 'long enough pw{Enter}')

    expect(await screen.findByRole('dialog', { name: 'Otto is invite-only right now.' })).toBeInTheDocument()
    expect(screen.getByLabelText('GitHub username or email')).toHaveValue('new@example.com')
    await userEvent.type(screen.getByLabelText('What would you use Otto for? (optional)'), 'my side project')
    await userEvent.click(screen.getByRole('button', { name: 'Request access' }))

    expect(await screen.findByRole('dialog', { name: 'Request sent' })).toBeInTheDocument()
    expect(posted.at(-1)).toEqual({ path: '/access-requests', body: { github_login: 'new@example.com', note: 'my side project' } })
  })

  it('invite-only: "Log in" goes back to the email', async () => {
    gateway({ exists: false, signup: () => HttpResponse.json({ error: 'invite_only', detail: 'x' }, { status: 403 }) })
    app('/login')
    await enterEmail('new@example.com')
    await userEvent.type(await screen.findByLabelText('Your name'), 'N')
    await userEvent.type(screen.getByLabelText('Password'), 'long enough pw{Enter}')
    await userEvent.click(await within(await screen.findByRole('dialog', { name: 'Otto is invite-only right now.' })).findByRole('button', { name: 'Log in' }))
    expect(screen.getByRole('dialog', { name: 'Log in or sign up' })).toBeInTheDocument()
  })

  it('paused: the offline state, with Watch the demo and Close', async () => {
    gateway({ exists: false, signup: () => HttpResponse.json({ error: 'paused', detail: 'x' }, { status: 503 }) })
    app('/login')
    await enterEmail('new@example.com')
    await userEvent.type(await screen.findByLabelText('Your name'), 'N')
    await userEvent.type(screen.getByLabelText('Password'), 'long enough pw{Enter}')
    const d = await screen.findByRole('dialog', { name: 'Otto is offline right now.' })
    expect(within(d).getByText('It runs on my own hardware to stay free.')).toBeInTheDocument()
    expect(within(d).getByRole('link', { name: 'Watch the demo' })).toHaveAttribute('href', 'https://otto.taufi.dev/#demo')
    await userEvent.click(within(d).getByRole('button', { name: 'Close' }))
    expect(screen.getByRole('dialog', { name: 'Log in or sign up' })).toBeInTheDocument()
  })
})

describe('when Otto can\'t be reached, or GitHub said no', () => {
  it('an unreachable gateway is the offline state', async () => {
    gateway({ status: () => HttpResponse.error() })
    app('/login')
    await enterEmail()
    expect(await screen.findByRole('dialog', { name: 'Otto is offline right now.' })).toBeInTheDocument()
  })

  it('a rate limit is an inline message', async () => {
    gateway({ status: () => HttpResponse.json({ error: 'rate_limited', detail: 'Too many attempts. Wait a minute and try again.' }, { status: 429 }) })
    app('/login')
    await enterEmail()
    expect(await within(dialog()).findByText('Too many attempts. Wait a minute and try again.')).toBeInTheDocument()
  })

  it.each([
    ['invite_only', 'Otto is invite-only right now.'],
    ['paused', 'Otto is offline right now.'],
  ])('a GitHub sign-up refused as %s opens that state', async (error, title) => {
    app(`/login?error=${error}`)
    expect(await screen.findByRole('dialog', { name: title })).toBeInTheDocument()
  })
})
