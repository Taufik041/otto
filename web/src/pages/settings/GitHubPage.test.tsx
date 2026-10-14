import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import { rememberReturn } from '@/auth/auth'
import { me } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { GitHubPage } from './GitHubPage'

function page(path: string, user = me) {
  renderSignedIn(
    <Routes>
      <Route path="/settings/github" element={<GitHubPage />} />
      <Route path="/welcome" element={<p>onboarding</p>} />
    </Routes>,
    { path, user },
  )
}

beforeEach(() => {
  server.use(
    http.get(`${API}/github`, () => HttpResponse.json({ connected: false, login: null, avatar_url: null, installations: [] })),
    http.get(`${API}/repos`, () => HttpResponse.json([])),
  )
})

describe('a GitHub link or install that failed', () => {
  it('a GitHub account linked to another Otto account is named, inline, and ?error leaves the URL', async () => {
    page('/settings/github?error=github_already_linked&login=octo', { ...me, github_login: null })
    expect(await screen.findByText("GitHub isn't connected.")).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'This GitHub account (@octo) is already linked to a different Otto account. Sign in with GitHub to use that account, or unlink it there first.',
    )
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/settings\/github$/))
  })

  it('an Otto account linked to another GitHub account names the linked one', async () => {
    page('/settings/github?error=github_account_mismatch&login=first')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your Otto account is already connected to GitHub as @first. Disconnect it in Settings → GitHub first to connect a different account.',
    )
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/settings\/github$/))
  })

  it.each([
    [
      'installation_taken',
      'This GitHub App installation is connected to a different Otto account. Ask its owner to disconnect it, or install the app on another account or org.',
    ],
    ['access_denied', 'Connecting GitHub was cancelled. Nothing changed.'],
    ['state_invalid', 'That GitHub sign-in expired or was started in another browser. Try again.'],
    ['github_unavailable', "GitHub didn't answer as expected. Try again in a minute."],
    ['unknown', "Connecting GitHub didn't finish. Try again."],
    ['something_new', "Connecting GitHub didn't finish. Try again."],
  ])('%s says so in plain words', async (error, message) => {
    page(`/settings/github?error=${error}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/settings\/github$/))
  })

  it('stays here to say why, even when onboarding started it', async () => {
    rememberReturn('/welcome')
    page('/settings/github?error=github_already_linked&login=octo', { ...me, github_login: null })
    expect(await screen.findByRole('alert')).toHaveTextContent('(@octo)')
    expect(screen.queryByText('onboarding')).not.toBeInTheDocument()
  })

  it('without an error, an install still goes back to the page that started it', async () => {
    rememberReturn('/welcome')
    page('/settings/github')
    expect(await screen.findByText('onboarding')).toBeInTheDocument()
  })
})
