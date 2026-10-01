import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { client } from '@/api'
import { GuestOnly, RequireAuth } from '@/auth/guards'
import { Where } from '@/test/render'
import { API, server } from '@/test/server'
import { tokenBody } from '@/test/fixtures'
import { LoginPage } from './LoginPage'

function app(path: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="*" element={<RequireAuth><p>the app</p></RequireAuth>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  server.use(http.post(`${API}/auth/logout`, () => HttpResponse.json({ ok: true })))
  await client.logout() // signed out
})

it('a cancelled GitHub sign-in lands on /login with a friendly message', async () => {
  app('/?github_error=access_denied')
  expect(await screen.findByText('GitHub sign-in was cancelled. Try again, or use your email.')).toBeInTheDocument()
  expect(screen.getByTestId('where')).toHaveTextContent('/login?github_error=access_denied')
})

it('a signed-out visit remembers where it was going', async () => {
  app('/settings/usage')
  expect(screen.getByTestId('where')).toHaveTextContent('/login?next=%2Fsettings%2Fusage')
})

it('a wrong password is an inline error; the right one goes to ?next', async () => {
  let ok = false
  server.use(
    http.post(`${API}/auth/login`, () =>
      ok ? HttpResponse.json(tokenBody()) : HttpResponse.json({ detail: 'wrong email or password' }, { status: 401 }),
    ),
  )
  app('/login?next=%2Fsettings%2Fusage')
  await userEvent.type(screen.getByLabelText('Email'), 'taufik@hey.com')
  await userEvent.type(screen.getByLabelText('Password'), 'nope')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByText("That password isn't right. Try again or reset it.")).toBeInTheDocument()

  ok = true
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByText('the app')).toBeInTheDocument()
  expect(screen.getByTestId('where')).toHaveTextContent('/settings/usage')
})
