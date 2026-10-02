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

function backend(events: SessionEvent[], detail: Record<string, unknown> = {}) {
  const posted: string[] = []
  server.use(
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
  expect(document.body.textContent).not.toMatch(/recreated|reused|warm sandbox|previous/i)
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
