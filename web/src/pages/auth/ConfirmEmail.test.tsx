import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import { client } from '@/api'
import type { Me } from '@/api/types'
import { RequireAuth } from '@/auth/guards'
import { me, tokenBody } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { VerifyPage } from './VerifyPage'

const unconfirmed: Me = { ...me, email: 'new@example.com', email_verified: false, github_login: null }

function app(user: Me = unconfirmed, path = '/') {
  const posted: { path: string; body: unknown }[] = []
  const log = (p: string, res: () => Response) =>
    http.post(`${API}${p}`, async ({ request }) => {
      posted.push({ path: p, body: await request.text().then((t) => (t ? JSON.parse(t) : null)) })
      return res()
    })
  server.use(
    log('/me/email/verify', () => HttpResponse.json({ ok: true, email: unconfirmed.email })),
    log('/me/email', () => HttpResponse.json({ ...unconfirmed, email: 'fixed@example.com' })),
    log('/auth/logout', () => HttpResponse.json({ ok: true })),
  )
  renderSignedIn(
    <Routes>
      <Route path="/verify-email" element={<VerifyPage />} />
      <Route path="/login" element={<p>sign in</p>} />
      <Route path="*" element={<RequireAuth><p>the app</p></RequireAuth>} />
    </Routes>,
    { path, user },
  )
  return posted
}

const heading = () => screen.findByRole('heading', { name: 'Confirm your email' })

describe('"Confirm your email": an email sign-up before it opens its link', () => {
  it('sees the screen instead of the app, with its address', async () => {
    app()
    expect(await heading()).toBeInTheDocument()
    expect(screen.queryByText('the app')).not.toBeInTheDocument()
    expect(screen.getByText('We sent a link to new@example.com. Open it to start using Otto. It expires in 24 hours.')).toBeInTheDocument()
  })

  it('a confirmed account, a GitHub one, or an older gateway sees the app', () => {
    for (const user of [me, { ...me, email: null, email_verified: false }, { ...unconfirmed, email_verified: undefined }]) {
      const { unmount } = renderSignedIn(<RequireAuth><p>the app</p></RequireAuth>, { user })
      expect(screen.getByText('the app')).toBeInTheDocument()
      unmount()
    }
  })

  it('Resend sends another link and says so', async () => {
    const posted = app()
    await userEvent.click(await screen.findByRole('button', { name: 'Resend' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Sent another link to new@example.com.')
    expect(posted.map((p) => p.path)).toEqual(['/me/email/verify'])
  })

  it('Resend past the limit says to wait', async () => {
    app()
    server.use(
      http.post(`${API}/me/email/verify`, () =>
        HttpResponse.json({ error: 'rate_limited', detail: 'Too many attempts. Wait a minute and try again.' }, { status: 429 }),
      ),
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Resend' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Wait a minute and try again.')
  })

  it('Change email sends a link to the new address', async () => {
    const posted = app()
    await userEvent.click(await screen.findByRole('button', { name: 'Change email' }))
    await userEvent.type(screen.getByLabelText('New email address'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Send link' }))
    expect(screen.getByText('Enter a valid email.')).toBeInTheDocument()
    expect(posted).toEqual([])

    await userEvent.clear(screen.getByLabelText('New email address'))
    await userEvent.type(screen.getByLabelText('New email address'), 'fixed@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send link' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Sent a link to fixed@example.com.')
    expect(posted).toEqual([{ path: '/me/email', body: { email: 'fixed@example.com' } }])
    expect(screen.getByText(/We sent a link to fixed@example.com\./)).toBeInTheDocument()
  })

  it('an address a confirmed account has is an inline error', async () => {
    app()
    server.use(http.post(`${API}/me/email`, () => HttpResponse.json({ detail: 'an account with this email already exists' }, { status: 409 })))
    await userEvent.click(await screen.findByRole('button', { name: 'Change email' }))
    await userEvent.type(screen.getByLabelText('New email address'), 'taken@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send link' }))
    expect(await screen.findByText('An account with this email already exists')).toBeInTheDocument()
  })

  it('Sign out signs out', async () => {
    app()
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(client.getState().status).toBe('signedOut'))
  })
})

describe('/verify-email: the link', () => {
  it('confirms the email, signs in and lands on the app', async () => {
    const posted: unknown[] = []
    server.use(
      http.post(`${API}/auth/verify`, async ({ request }) => {
        posted.push({ path: '/auth/verify', body: await request.json() })
        return HttpResponse.json({ ...tokenBody('tok-2'), user: { ...unconfirmed, email_verified: true } })
      }),
    )
    app(unconfirmed, '/verify-email?token=t1')
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/)
    expect(posted).toEqual([{ path: '/auth/verify', body: { token: 't1' } }])
    expect(client.getState().user?.email_verified).toBe(true)
  })

  it('signed in and confirmed already: straight to the app, nothing asked', async () => {
    let asked = false
    server.use(http.post(`${API}/auth/verify`, () => ((asked = true), HttpResponse.json({}, { status: 400 }))))
    app(me, '/verify-email?token=t1')
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(asked).toBe(false)
  })

  it('an expired or used link says so', async () => {
    server.use(
      http.post(`${API}/auth/verify`, () =>
        HttpResponse.json({ detail: 'this confirmation link is invalid or has expired; ask for a new one' }, { status: 400 }),
      ),
    )
    app(unconfirmed, '/verify-email?token=old')
    expect(await screen.findByRole('heading', { name: 'That link didn’t work' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('This confirmation link is invalid or has expired; ask for a new one.')
  })
})
