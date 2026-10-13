import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import type { Me } from '@/api/types'
import { me } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { AccountPage } from './AccountPage'

const githubMade: Me = { ...me, email: 'taufik@hey.com', has_password: false, github_login: 'Taufik041' }

function page(user: Me = githubMade, answer: () => Response = () => HttpResponse.json({ ok: true, email: user.email })) {
  const posted: string[] = []
  server.use(
    http.post(`${API}/me/password/setup`, () => {
      posted.push('setup')
      return answer()
    }),
  )
  renderSignedIn(<Routes><Route path="/settings/account" element={<AccountPage />} /></Routes>, { path: '/settings/account', user })
  return posted
}

const passwordRow = () => screen.getByText('Password').parentElement!

describe('Settings → Account: the password of an account made with GitHub', () => {
  it('"Set a password" emails a link to the account\'s address and says so', async () => {
    const posted = page()
    await userEvent.click(within(passwordRow()).getByRole('button', { name: 'Set a password' }))
    await waitFor(() => expect(posted).toEqual(['setup']))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'We emailed a link to taufik@hey.com. Open it within 1 hour to set your password, then log in with your email and password too.',
    )
  })

  it('a failure says why, in plain words', async () => {
    page(githubMade, () => HttpResponse.json({ error: 'email_failed', detail: "That didn't send. Try again in a minute." }, { status: 502 }))
    await userEvent.click(within(passwordRow()).getByRole('button', { name: 'Set a password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("That didn't send. Try again in a minute.")
  })

  it('without an email there is nowhere to send it: it signs in with GitHub', () => {
    page({ ...githubMade, email: null })
    expect(within(passwordRow()).getByText('Signs in with GitHub')).toBeInTheDocument()
    expect(within(passwordRow()).queryByRole('button', { name: 'Set a password' })).not.toBeInTheDocument()
  })

  it('an account with a password changes it as before', () => {
    page({ ...me, has_password: true })
    expect(within(passwordRow()).getByRole('button', { name: 'Change password' })).toBeInTheDocument()
  })
})
