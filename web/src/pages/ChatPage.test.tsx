import { act, getDefaultNormalizer, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router'
import type { SessionEvent } from '@/chat/reduce'
import { AppShell } from '@/shell/AppShell'
import { log, mainRun } from '@/test/events'
import { models, session } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { ChatPage } from './ChatPage'

/** A WebSocket that connects when told to, and delivers what the test sends. */
class FakeSocket {
  static all: FakeSocket[] = []
  onopen: ((e: unknown) => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.all.push(this)
  }
  close() {}
  deliver(e: SessionEvent) {
    act(() => this.onmessage?.({ data: JSON.stringify(e) }))
  }
}

beforeEach(() => {
  FakeSocket.all = []
  vi.stubGlobal('WebSocket', FakeSocket)
  Element.prototype.scrollTo = () => {}
  Element.prototype.scrollIntoView = () => {}
})

/** extra: handlers that win over these defaults, in place before the first render */
function backend(events: SessionEvent[], detail: Record<string, unknown> = {}, extra: Parameters<typeof server.use> = []) {
  const posted: string[] = []
  server.use(
    ...extra,
    http.get(`${API}/sessions`, () => HttpResponse.json([session({ id: 's1' })])),
    http.get(`${API}/sessions/s1`, () =>
      HttpResponse.json({
        ...session({ id: 's1' }),
        task: 't',
        repo_url: null,
        work_branch: 'otto/4299fa2c3f',
        created_at: '2026-10-02T14:00:00Z',
        ...detail,
      }),
    ),
    http.get(`${API}/sessions/s1/events`, ({ request }) => {
      const after = Number(new URL(request.url).searchParams.get('after_seq') ?? 0)
      return HttpResponse.json(events.filter((e) => e.seq > after))
    }),
    http.post(`${API}/sessions/s1/ws-ticket`, () => HttpResponse.json({ ticket: 'tk' })),
    http.post(`${API}/sessions/s1/retry`, () => {
      posted.push('retry')
      return HttpResponse.json({ id: 's1', status: 'queued' }, { status: 202 })
    }),
    http.get(`${API}/models`, () => HttpResponse.json({ default_model: 'openrouter:openrouter/free', models })),
    http.get(`${API}/repos`, () => HttpResponse.json([])),
  )
  renderSignedIn(
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/c/:id" element={<ChatPage />} />
      </Route>
    </Routes>,
    { path: '/c/s1' },
  )
  return { posted }
}

it('shows a finished run: the message, the collapsed block, the PR card and the reply', async () => {
  backend(mainRun().events)
  expect(await screen.findByText('two tests are failing, find out why and fix the source, not the tests')).toBeInTheDocument()
  expect(screen.getByText("On it. I'll reproduce the failures first.")).toBeInTheDocument()
  const toggle = screen.getByRole('button', { name: /7 steps · 9 passed/ })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('Pull request opened')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /View on GitHub/ })).toHaveAttribute('href', 'https://github.com/Taufik041/otto_test/pull/3')
  expect(screen.getByText('9 tests passed')).toBeInTheDocument()
  expect(screen.getByText('otto/4299fa2c3f → main')).toBeInTheDocument()

  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('2 failed, 7 passed')).toBeInTheDocument()
})

it('"See changes" opens the workspace on the diff; Terminal lists the commands', async () => {
  backend(mainRun().events)
  await userEvent.click(await screen.findByRole('link', { name: 'See changes ›' }))
  const panel = screen.getByRole('region', { name: 'Workspace' })
  expect(within(panel).getByText('Unified diff')).toBeInTheDocument()
  expect(within(panel).getByText('    return quantity >= 10', { normalizer: getDefaultNormalizer({ trim: false, collapseWhitespace: false }) })).toBeInTheDocument()
  expect(within(panel).getAllByText('src/inventory/pricing.py').length).toBeGreaterThan(0)

  await userEvent.click(within(panel).getByRole('tab', { name: 'Terminal' }))
  expect(within(panel).getAllByText('python -m pytest -q')).toHaveLength(2)
  expect(within(panel).getByText('git push -u origin otto/4299fa2c3f')).toBeInTheDocument()
  expect(within(panel).getByText('exit 1')).toBeInTheDocument()
  expect(within(panel).queryByText(/gh pr/)).not.toBeInTheDocument()
})

it('goes live over the WebSocket after the stored events, and hides infrastructure events', async () => {
  const l = log().created('fix it').status('provisioning')
  backend(l.events)
  expect(await screen.findByText('Setting up workspace…')).toBeInTheDocument()
  await waitFor(() => expect(FakeSocket.all).toHaveLength(1))
  const sock = FakeSocket.all[0]!
  expect(sock.url).toBe('ws://localhost:8000/sessions/s1/ws?ticket=tk&after_seq=2')

  sock.deliver({ seq: 3, ts: '2026-10-02T14:02:10Z', type: 'sandbox.recreated', payload: { previous: 'finished' } })
  sock.deliver({ seq: 4, ts: '2026-10-02T14:02:11Z', type: 'session.status', payload: { status: 'running' } })
  sock.deliver({ seq: 5, ts: '2026-10-02T14:02:12Z', type: 'bus.action', payload: { action_id: 'x', kind: 'shell.exec', payload: { cmd: 'pytest' } } })
  sock.deliver({ seq: 5, ts: '2026-10-02T14:02:12Z', type: 'bus.action', payload: { action_id: 'x', kind: 'shell.exec', payload: { cmd: 'pytest' } } })

  expect(await screen.findByText('Running')).toBeInTheDocument()
  expect(screen.getAllByText('pytest')).toHaveLength(1) // the duplicate seq is dropped
  expect(document.body.textContent).not.toMatch(/recreated|reused|warm sandbox/i) // ("previous" would match the sidebar's "Previous 7 days")
  expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
})

it('a failed run shows the error card, and Retry asks the gateway to run it again', async () => {
  const l = log().created('fix it').status('running')
    .act('git.status', {})
    .add('error', { stage: 'llm', message: 'no usable LLM response after 6 attempts' })
    .status('failed')
  const { posted } = backend(l.events)
  expect(await screen.findByText("Otto couldn't finish.")).toBeInTheDocument()
  expect(screen.getByText("The model didn't respond after 6 tries. Nothing was committed. Retry to continue from the last step.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(posted).toEqual(['retry']))
})

it('a plain chat shows only messages and the nudge to mention a repo', async () => {
  const l = log().created('what is a closure?', null).status('running')
    .msg('user', 'what is a closure?').msg('assistant', 'A function that **remembers** its scope.').status('done')
  backend(l.events, { repo: null, work_branch: null })
  expect(await screen.findByText('remembers')).toBeInTheDocument()
  expect(screen.queryByText(/Working in|steps/)).not.toBeInTheDocument()
  expect(screen.getByText("Mention a repo with @ and I'll work on it.")).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Workspace' })).not.toBeInTheDocument()
})

it('a model switch shows as a divider, and the header follows it', async () => {
  const l = log().created('what is a closure?', null).status('running')
    .msg('user', 'what is a closure?').msg('assistant', 'A function.').status('done')
  backend(l.events, { repo: null, work_branch: null, model: 'openrouter:openrouter/free' })
  const header = await screen.findByRole('banner')
  expect(within(header).getByText('OpenRouter Free')).toBeInTheDocument()

  await waitFor(() => expect(FakeSocket.all).toHaveLength(1))
  FakeSocket.all[0]!.deliver({ seq: 6, ts: '2026-10-02T14:10:00Z', type: 'session.status', payload: { status: 'provisioning' } })
  FakeSocket.all[0]!.deliver({ seq: 7, ts: '2026-10-02T14:10:00Z', type: 'session.model_changed', payload: { from: 'openrouter:openrouter/free', to: 'openai:gpt-4.1-mini' } })
  FakeSocket.all[0]!.deliver({ seq: 8, ts: '2026-10-02T14:10:01Z', type: 'llm.message', payload: { message: { role: 'user', content: 'and in Python?' } } })

  expect(await screen.findByRole('separator', { name: 'Switched to GPT-4.1 mini' })).toBeInTheDocument()
  expect(within(header).getByText('GPT-4.1 mini')).toBeInTheDocument()
  expect(screen.getByText('and in Python?')).toBeInTheDocument()
})

it('an auto title (session.titled) updates the header and the sidebar live', async () => {
  const l = log().created('hey so what is a closure, like in javascript', null).status('running')
    .msg('user', 'hey so what is a closure, like in javascript').msg('assistant', 'A function.')
  let listTitle = 'hey so what is a closure, like in javascript'
  backend(l.events, { repo: null, work_branch: null, title: listTitle })
  server.use(http.get(`${API}/sessions`, () => HttpResponse.json([session({ id: 's1', repo: null, title: listTitle })])))
  const header = await screen.findByRole('banner')
  expect(within(header).getByText(listTitle)).toBeInTheDocument()
  await waitFor(() => expect(FakeSocket.all).toHaveLength(1))

  listTitle = 'Closures in JavaScript' // what GET /sessions answers once the brain titled it
  FakeSocket.all[0]!.deliver({ seq: 5, ts: '2026-10-02T14:10:00Z', type: 'session.status', payload: { status: 'done' } })
  FakeSocket.all[0]!.deliver({ seq: 6, ts: '2026-10-02T14:10:01Z', type: 'session.titled', payload: { title: 'Closures in JavaScript', source: 'model' } })

  await waitFor(() => expect(within(header).getByText('Closures in JavaScript')).toBeInTheDocument())
  const sidebar = screen.getByRole('navigation', { name: 'Chats' })
  await waitFor(() => expect(within(sidebar).getByText('Closures in JavaScript')).toBeInTheDocument())
})

it('out of credit: the card says so, offers the picker, and Retry runs on the model picked', async () => {
  const l = log().created('what is a closure?', null).status('running')
    .add('error', { stage: 'model', reason: 'quota', provider: 'openrouter', model: null, message: 'openrouter is unusable: quota' })
    .status('failed')
  const bodies: unknown[] = []
  backend(l.events, { repo: null, work_branch: null, model: 'openrouter:openrouter/free' }, [
    http.get(`${API}/models`, () =>
      HttpResponse.json({
        default_model: 'openrouter:openrouter/free',
        models: [
          { id: 'openrouter:openrouter/free', label: 'OpenRouter Free', provider: 'openrouter', available: false,
            hint: 'Out of credit right now. Try another model.' },
          { id: 'openai:gpt-4.1-mini', label: 'GPT-4.1 mini', provider: 'openai', available: true, hint: null },
        ],
      }),
    ),
    http.post(`${API}/sessions/s1/retry`, async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json({ id: 's1', status: 'queued' }, { status: 202 })
    }),
  ])

  const card = await screen.findByRole('alert')
  expect(within(card).getByText("This model's provider is out of credit.")).toBeInTheDocument()
  expect(within(card).getByText('Switch models and retry.')).toBeInTheDocument()

  await userEvent.click(within(card).getByRole('button', { name: /OpenRouter Free/ }))
  expect(within(card).getByRole('option', { name: /OpenRouter Free/ })).toHaveAttribute('aria-disabled', 'true')
  expect(within(card).getByText('Out of credit right now. Try another model.')).toBeInTheDocument()
  await userEvent.click(within(card).getByRole('option', { name: /GPT-4.1 mini/ }))
  await userEvent.click(within(card).getByRole('button', { name: 'Retry' }))

  await waitFor(() => expect(bodies).toEqual([{ model: 'openai:gpt-4.1-mini' }]))
})

it('a bad key says the model isn\'t set up correctly', async () => {
  const l = log().created('t', null).status('running')
    .add('error', { stage: 'model', reason: 'auth', provider: 'openai', model: null, message: 'x' }).status('failed')
  backend(l.events, { repo: null, work_branch: null })
  const card = await screen.findByRole('alert')
  expect(within(card).getByText("This model isn't set up correctly.")).toBeInTheDocument()
  expect(within(card).getByText('Try another model.')).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

describe('the proposed pull request', () => {
  const PROPOSAL = {
    title: 'Fix failing pricing tests', body: 'Found it.', head: 'otto/s1', base: 'main',
    additions: 1, deletions: 1, files: 1, tests: { passed: 9, failed: 0, text: '9 passed' },
  }
  function proposed(status = 'done') {
    const l = log().created('fix the tests').status('running')
      .act('git.push', {}, { exit_code: 0, stdout: '', stderr: '', branch: 'otto/s1', base: 'main', diffstat: { files: 1, additions: 1, deletions: 1 } })
      .msg('assistant', 'Found it.')
      .add('pr.proposed', PROPOSAL)
    if (status !== 'running') l.status(status)
    return l
  }
  function prRoutes(create?: () => Response | Promise<Response>) {
    const calls: string[] = []
    return {
      calls,
      handlers: [
        http.post(`${API}/sessions/s1/pr`, async () => {
          calls.push('create')
          return create ? create() : HttpResponse.json({ number: 3, url: 'https://github.com/Taufik041/otto_test/pull/3', title: 'x', created: true }, { status: 201 })
        }),
        http.post(`${API}/sessions/s1/pr/decline`, () => {
          calls.push('decline')
          return HttpResponse.json({ ok: true })
        }),
      ],
    }
  }
  const prCard = () => screen.getByRole('region', { name: 'Ready for review' })

  it('shows the proposal; Create opens it, and the card becomes the PR card', async () => {
    const { calls, handlers } = prRoutes()
    backend(proposed().events, {}, handlers)
    const card = await screen.findByRole('region', { name: 'Ready for review' })
    expect(within(card).getByText('Fix failing pricing tests')).toBeInTheDocument()
    expect(within(card).getByText('Taufik041/otto_test · otto/s1 → main')).toBeInTheDocument()
    expect(within(card).getByText('9 tests passed')).toBeInTheDocument()
    expect(within(card).getByText('1 file')).toBeInTheDocument()

    await userEvent.click(within(card).getByRole('button', { name: 'Create pull request' }))
    await waitFor(() => expect(calls).toEqual(['create']))
    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0))
    FakeSocket.all.at(-1)!.deliver({ seq: 9, ts: '2026-10-02T14:10:00Z', type: 'pr.opened', payload: { number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3' } })

    expect(await screen.findByText('Pull request opened')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Ready for review' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View on GitHub/ })).toHaveAttribute('href', 'https://github.com/Taufik041/otto_test/pull/3')
  })

  it('Create shows a spinner and is disabled while it runs', async () => {
    const { handlers } = prRoutes(() => new Promise(() => {})) // never answers
    backend(proposed().events, {}, handlers)
    const create = await within(await screen.findByRole('region', { name: 'Ready for review' })).findByRole('button', { name: 'Create pull request' })
    await userEvent.click(create)
    await waitFor(() => expect(create).toBeDisabled())
    expect(create).toHaveAttribute('aria-busy', 'true')
  })

  it('an error shows under the buttons', async () => {
    const { handlers } = prRoutes(() =>
      HttpResponse.json({ detail: "GitHub didn't open the pull request: Validation Failed" }, { status: 502 }),
    )
    backend(proposed().events, {}, handlers)
    await userEvent.click(await within(await screen.findByRole('region', { name: 'Ready for review' })).findByRole('button', { name: 'Create pull request' }))
    expect(await within(prCard()).findByText("GitHub didn't open the pull request: Validation Failed")).toBeInTheDocument()
    expect(within(prCard()).getByRole('button', { name: 'Create pull request' })).toBeEnabled()
  })

  it('Not now collapses it to a quiet line whose link still creates it', async () => {
    const { calls, handlers } = prRoutes()
    backend(proposed().events, {}, handlers)
    await userEvent.click(await within(await screen.findByRole('region', { name: 'Ready for review' })).findByRole('button', { name: 'Not now' }))
    await waitFor(() => expect(calls).toEqual(['decline']))
    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0))
    FakeSocket.all.at(-1)!.deliver({ seq: 9, ts: '2026-10-02T14:10:00Z', type: 'pr.declined', payload: {} })

    expect(await screen.findByText('Pull request not created')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create pull request' }))
    await waitFor(() => expect(calls).toEqual(['decline', 'create']))
  })

  it('the buttons are disabled while Otto works', async () => {
    const { handlers } = prRoutes()
    backend(proposed('running').events, {}, handlers)
    const card = await screen.findByRole('region', { name: 'Ready for review' })
    expect(within(card).getByRole('button', { name: 'Create pull request' })).toBeDisabled()
    expect(within(card).getByRole('button', { name: 'Not now' })).toBeDisabled()
    expect(within(card).getByText('Otto is working…')).toBeInTheDocument()
  })
})

describe('seen: the open chat never wants attention', () => {
  /** /sessions answers like the gateway: "done" until a seen at or past the end */
  function server_(endSeq: { v: number }, status: { v: string }) {
    const log: string[] = []
    let seen = 0
    return {
      log,
      handlers: [
        http.post(`${API}/sessions/s1/seen`, async ({ request }) => {
          const { seq } = (await request.json()) as { seq: number }
          seen = Math.max(seen, seq)
          log.push(`seen:${seq}`)
          return HttpResponse.json({ last_seen_seq: seen })
        }),
        http.get(`${API}/sessions`, () => {
          const attention = status.v === 'running' ? 'working' : endSeq.v > seen ? 'done' : null
          log.push(`list:${attention}`)
          return HttpResponse.json([{ ...session({ id: 's1', repo: null }), attention }])
        }),
      ],
    }
  }
  const dot = (name: string) => within(screen.getByRole('navigation', { name: 'Chats' })).queryByRole('img', { name })

  it('opening a chat marks it seen, and its dot goes', async () => {
    const l = log().created('hi', null).status('running').msg('user', 'hi').msg('assistant', 'Hello.').status('done')
    const { log: calls, handlers } = server_({ v: l.events.length }, { v: 'done' })
    backend(l.events, { repo: null, work_branch: null }, handlers)

    await waitFor(() => expect(calls).toContain(`seen:${l.events.length}`))
    await waitFor(() => expect(dot('Done')).not.toBeInTheDocument())
  })

  it('a turn that finishes while you watch never shows a dot', async () => {
    const l = log().created('hi', null).status('running').msg('user', 'hi')
    const end = { v: 0 }
    const status = { v: 'running' }
    const { log: calls, handlers } = server_(end, status)
    backend(l.events, { repo: null, work_branch: null, status: 'running' }, handlers)
    await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0))
    await waitFor(() => expect(dot('Working')).toBeInTheDocument())
    calls.length = 0

    status.v = 'done'
    end.v = 5
    FakeSocket.all.at(-1)!.deliver({ seq: 4, ts: '2026-10-02T14:10:00Z', type: 'llm.message', payload: { message: { role: 'assistant', content: 'Hi.' } } })
    FakeSocket.all.at(-1)!.deliver({ seq: 5, ts: '2026-10-02T14:10:01Z', type: 'session.status', payload: { status: 'done' } })

    await waitFor(() => expect(calls).toContain('seen:5'))
    await waitFor(() => expect(calls.some((c) => c.startsWith('list:'))).toBe(true))
    // the list is only asked again after the seen post, so it never answers "done" meanwhile
    expect(calls.indexOf('seen:5')).toBeLessThan(calls.findIndex((c) => c.startsWith('list:')))
    expect(calls).not.toContain('list:done')
    expect(dot('Done')).not.toBeInTheDocument()
  })

  it('a hidden tab doesn\'t mark it seen until it becomes visible again', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const l = log().created('hi', null).status('running').msg('user', 'hi').msg('assistant', 'Hello.').status('done')
    const { log: calls, handlers } = server_({ v: l.events.length }, { v: 'done' })
    backend(l.events, { repo: null, work_branch: null }, handlers)
    await screen.findByText('Hello.')
    await new Promise((r) => setTimeout(r, 700)) // longer than the debounce
    expect(calls.filter((c) => c.startsWith('seen'))).toEqual([])

    visibility.mockReturnValue('visible')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await waitFor(() => expect(calls).toContain(`seen:${l.events.length}`))
  })
})
