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

vi.mock('@/utils/links', async (original) => ({ ...(await original<typeof import('@/utils/links')>()), goToLanding: vi.fn() }))

describe('Settings → Account → Delete account', () => {
  function deleting(user: Me, answer: () => Response = () => HttpResponse.json({ ok: true })) {
    const sent: unknown[] = []
    server.use(
      http.delete(`${API}/me`, async ({ request }) => {
        sent.push(await request.json())
        return answer()
      }),
      http.post(`${API}/auth/logout`, () => HttpResponse.json({ ok: true })),
      http.get(`${API}/github`, () =>
        HttpResponse.json({
          connected: true, login: 'Taufik041', avatar_url: null,
          installations: [{ id: 555, account_login: 'Taufik041', uninstall_url: 'https://github.com/settings/installations/555' }],
        }),
      ),
    )
    renderSignedIn(<Routes><Route path="/settings/account" element={<AccountPage />} /></Routes>, { path: '/settings/account', user })
    return sent
  }

  const open = async () => {
    await userEvent.click(screen.getByRole('button', { name: 'Delete account' }))
    return screen.findByRole('dialog', { name: 'Delete your account?' })
  }

  it('explains what happens: deactivated now, deleted within 30 days, PRs stay, uninstall the App on GitHub', async () => {
    deleting({ ...me, has_password: true })
    const dialog = await open()
    expect(dialog).toHaveTextContent('deactivated right away')
    expect(dialog).toHaveTextContent('permanently deleted within 30 days')
    expect(dialog).toHaveTextContent('Pull requests Otto already opened live in your own repositories on GitHub, and they stay there.')
    expect(await within(dialog).findByRole('link', { name: 'Taufik041 ›' })).toHaveAttribute(
      'href', 'https://github.com/settings/installations/555',
    )
  })

  it('needs DELETE typed and the password; then it deletes and goes to the landing page', async () => {
    const { goToLanding } = await import('@/utils/links')
    const sent = deleting({ ...me, has_password: true })
    const dialog = await open()
    const button = within(dialog).getByRole('button', { name: 'Delete account' })
    await userEvent.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'delete')
    expect(button).toBeDisabled()
    await userEvent.clear(within(dialog).getByLabelText('Type DELETE to confirm'))
    await userEvent.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'DELETE')
    expect(button).toBeDisabled() // and the password
    await userEvent.type(within(dialog).getByLabelText('Password'), 'correct horse')
    await userEvent.click(button)
    await waitFor(() => expect(goToLanding).toHaveBeenCalled())
    expect(sent).toEqual([{ confirm: 'DELETE', password: 'correct horse' }])
  })

  it('a wrong password says so, and nothing is deleted', async () => {
    const { goToLanding } = await import('@/utils/links')
    vi.mocked(goToLanding).mockClear()
    deleting({ ...me, has_password: true }, () => HttpResponse.json({ detail: 'the password is wrong' }, { status: 403 }))
    const dialog = await open()
    await userEvent.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'DELETE')
    await userEvent.type(within(dialog).getByLabelText('Password'), 'nope nope')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete account' }))
    expect(await within(dialog).findByText("That password isn't right.")).toBeInTheDocument()
    expect(goToLanding).not.toHaveBeenCalled()
  })

  it('an account without a password only types DELETE', async () => {
    const sent = deleting(githubMade)
    const dialog = await open()
    expect(within(dialog).queryByLabelText('Password')).not.toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'DELETE')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete account' }))
    await waitFor(() => expect(sent).toEqual([{ confirm: 'DELETE', password: null }]))
  })
})
