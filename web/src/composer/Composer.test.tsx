import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Composer, DISCLAIMER, REPO_DISCLAIMER } from './Composer'
import type { NewSession, Repo } from '@/api/types'
import { me, models, repos } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'

function api({ repoList = repos, create }: { repoList?: Repo[]; create?: () => Response } = {}) {
  const sent: NewSession[] = []
  server.use(
    http.get(`${API}/models`, () => HttpResponse.json({ default_model: 'openrouter:openrouter/free', models })),
    http.get(`${API}/repos`, () => HttpResponse.json(repoList)),
    http.post(`${API}/sessions`, async ({ request }) => {
      sent.push((await request.json()) as NewSession)
      return create?.() ?? HttpResponse.json({ id: 'abc123', status: 'queued', title: 't', repo: null }, { status: 201 })
    }),
  )
  return sent
}

const box = () => screen.getByRole('textbox', { name: 'Message Otto' })

async function ready() {
  renderSignedIn(<Composer mobile={false} hero />)
  await screen.findByRole('button', { name: /OpenRouter Free/ }) // models loaded, default preselected
}

it('@ opens the repo picker, filters as you type, and Enter inserts a chip', async () => {
  api()
  await ready()
  await userEvent.type(box(), 'fix @')

  const list = await screen.findByRole('listbox')
  expect(within(list).getAllByRole('option')).toHaveLength(3)
  expect(within(list).getAllByText(/^updated .+ ago$/)).toHaveLength(3)

  await userEvent.type(box(), 'p')
  expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual([
    expect.stringContaining('portfolio'),
    expect.stringContaining('petal'),
  ])
  await userEvent.keyboard('{ArrowDown}{Enter}')

  expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Remove Taufik041/petal' })).toBeInTheDocument()
  expect(box()).toHaveValue('fix ')
})

it('sends the message, repo and model, then opens the chat', async () => {
  const sent = api()
  await ready()
  expect(screen.getByText(DISCLAIMER)).toBeInTheDocument()

  await userEvent.type(box(), '@otto')
  await userEvent.keyboard('{Enter}')
  expect(screen.getByText(REPO_DISCLAIMER)).toBeInTheDocument()
  // Otto proposes the PR; the user opens it
  expect(REPO_DISCLAIMER).toBe(
    'Otto works in a sandbox and proposes a pull request for you to review. Otto uses AI models and can make mistakes, so review changes before merging.',
  )
  await userEvent.type(box(), 'fix the failing tests{Enter}')

  await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/c/abc123'))
  expect(sent).toEqual([
    { message: 'fix the failing tests', repo: 'Taufik041/otto_test', model: 'openrouter:openrouter/free' },
  ])
})

it('a typed @repo without picking still attaches it; Shift+Enter is a new line', async () => {
  const sent = api()
  await ready()
  await userEvent.type(box(), 'explain this')
  await userEvent.keyboard('{Shift>}{Enter}{/Shift}')
  await userEvent.type(box(), 'in @petal ')
  await userEvent.keyboard('{Escape}{Enter}')

  await waitFor(() => expect(sent).toHaveLength(1))
  expect(sent[0]).toMatchObject({ message: 'explain this\nin', repo: 'Taufik041/petal' })
})

it('the model picker changes the model sent', async () => {
  const sent = api()
  await ready()
  await userEvent.click(screen.getByRole('button', { name: /OpenRouter Free/ }))
  await userEvent.click(screen.getByRole('option', { name: /GPT-4\.1 mini/ }))
  await userEvent.type(box(), 'hello{Enter}')
  await waitFor(() => expect(sent[0]?.model).toBe('openai:gpt-4.1-mini'))
})

it('with no repos, @ offers to install Otto on one', async () => {
  api({ repoList: [] })
  await ready()
  await userEvent.type(box(), '@')
  expect(await screen.findByText('Install Otto on a repository')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Install on repositories/ })).toBeInTheDocument()
})

it("without GitHub linked, @ says to connect it", async () => {
  api({ repoList: [] })
  renderSignedIn(<Composer mobile={false} hero />, { user: { ...me, github_login: null } })
  await userEvent.type(box(), '@')
  expect(await screen.findByText('Connect GitHub to mention repos')).toBeInTheDocument()
})

it('shows the daily limit inline', async () => {
  api({
    create: () =>
      HttpResponse.json({ code: 'daily_limit', used: 50000, limit: 50000, resets_at: '2026-10-02T00:00:00+00:00' }, { status: 429 }),
  })
  await ready()
  await userEvent.type(box(), 'hello{Enter}')
  expect(await screen.findByText("You've used today's limit.")).toBeInTheDocument()
  expect(screen.getByText('50,000 of 50,000 tokens')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'View usage ›' })).toHaveAttribute('href', '/settings/usage')
  expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/)
})

it('shows the active-sessions cap inline', async () => {
  api({
    create: () =>
      HttpResponse.json({ detail: 'you have 3 agent sessions at work already; wait for one to finish, or stop one' }, { status: 429 }),
  })
  await ready()
  await userEvent.type(box(), '@otto')
  await userEvent.keyboard('{Enter}')
  await userEvent.type(box(), 'go{Enter}')
  expect(await screen.findByText('Otto is busy right now.')).toBeInTheDocument()
  expect(screen.getByText('You have 3 agent sessions at work already; wait for one to finish, or stop one.')).toBeInTheDocument()
})

it('shows an unavailable model inline', async () => {
  api({
    create: () =>
      HttpResponse.json(
        { detail: [{ loc: ['body', 'model'], msg: "Value error, unknown or unavailable model 'x'; see GET /models" }] },
        { status: 422 },
      ),
  })
  await ready()
  await userEvent.type(box(), 'hello{Enter}')
  expect(await screen.findByText('Pick another model.')).toBeInTheDocument()
})

it('Send is disabled without text', async () => {
  api()
  await ready()
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  await userEvent.type(box(), '   ')
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
})

describe('workers offline (GET /health)', () => {
  const offline = () =>
    server.use(http.get(`${API}/health`, () => HttpResponse.json({ status: 'up', workers: 'offline', version: 't' })))
  const NOTICE = "Otto's workers are offline right now. Plain chat still works."

  it('says so above the box; a plain message still sends', async () => {
    offline()
    const sent = api()
    await ready()
    expect(await screen.findByText(NOTICE)).toBeInTheDocument()
    await userEvent.type(box(), 'what is a closure?{Enter}')
    await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'what is a closure?', repo: null })]))
  })

  it('a repo task can\'t be sent', async () => {
    offline()
    const sent = api()
    await ready()
    await screen.findByText(NOTICE)
    await userEvent.type(box(), '@otto{Enter}fix the tests')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await userEvent.type(box(), '{Enter}')
    expect(sent).toEqual([])
  })

  it('online: no notice, and repo tasks send', async () => {
    const sent = api()
    await ready()
    await userEvent.type(box(), '@otto{Enter}fix the tests{Enter}')
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument()
  })

  it('"Ask Taufik to bring it up" emails him once, then says he has been notified', async () => {
    offline()
    api()
    const asked: unknown[] = []
    server.use(
      http.post(`${API}/wake-requests`, async ({ request }) => {
        asked.push(await request.json())
        return HttpResponse.json({ ok: true }, { status: 202 })
      }),
    )
    await ready()
    await userEvent.click(await screen.findByRole('button', { name: 'Ask Taufik to bring it up' }))
    expect(await screen.findByText('Taufik has been notified.')).toBeInTheDocument()
    expect(asked).toEqual([{ message: '' }])
    expect(screen.queryByRole('button', { name: 'Ask Taufik to bring it up' })).not.toBeInTheDocument()
  })

  it('asked within the hour already (429): he has been notified', async () => {
    offline()
    api()
    server.use(
      http.post(`${API}/wake-requests`, () =>
        HttpResponse.json({ error: 'rate_limited', detail: 'Too many requests.' }, { status: 429 }),
      ),
    )
    await ready()
    await userEvent.click(await screen.findByRole('button', { name: 'Ask Taufik to bring it up' }))
    expect(await screen.findByText('Taufik has been notified.')).toBeInTheDocument()
  })

  it('an email that can\'t go out says why, and can be tried again', async () => {
    offline()
    api()
    server.use(
      http.post(`${API}/wake-requests`, () =>
        HttpResponse.json({ error: 'email_failed', detail: "The email didn't go out. Try again in a minute." }, { status: 502 }),
      ),
    )
    await ready()
    await userEvent.click(await screen.findByRole('button', { name: 'Ask Taufik to bring it up' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("The email didn't go out")
    expect(screen.getByRole('button', { name: 'Ask Taufik to bring it up' })).toBeEnabled()
  })

  it('a send refused with workers_offline shows the notice', async () => {
    api({
      create: () =>
        HttpResponse.json({ error: 'workers_offline', detail: NOTICE }, { status: 503 }),
    })
    await ready()
    offline() // what /health answers once asked again
    await userEvent.type(box(), '@otto{Enter}fix the tests{Enter}')
    expect(await screen.findByText(NOTICE)).toBeInTheDocument()
    expect(screen.queryByText(/model isn.t available/)).not.toBeInTheDocument()
  })
})
