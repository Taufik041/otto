import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Composer, type Reply } from './Composer'
import { models, repos } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'

function setup(reply: Partial<Reply> = {}, follow?: () => Response) {
  const calls: { path: string; body: unknown }[] = []
  server.use(
    http.get(`${API}/models`, () => HttpResponse.json({ default_model: 'openrouter:openrouter/free', models })),
    http.get(`${API}/repos`, () => HttpResponse.json(repos)),
    http.post(`${API}/sessions/s1/messages`, async ({ request }) => {
      calls.push({ path: 'messages', body: await request.json() })
      return follow?.() ?? HttpResponse.json({ id: 's1', status: 'queued', repo: null }, { status: 202 })
    }),
    http.post(`${API}/sessions/s1/stop`, () => {
      calls.push({ path: 'stop', body: null })
      return HttpResponse.json({ id: 's1', status: 'stopped' })
    }),
  )
  const onSent = vi.fn()
  renderSignedIn(
    <Composer
      mobile={false}
      hero={false}
      reply={{ sessionId: 's1', live: false, model: 'openai:gpt-4.1-mini', repo: 'Taufik041/otto_test', onSent, ...reply }}
    />,
  )
  return { calls, onSent }
}

const box = () => screen.getByRole('textbox', { name: 'Message Otto' })

it('while Otto works: Stop instead of Send, and Enter sends nothing', async () => {
  const { calls } = setup({ live: true })
  expect(box()).toHaveAttribute('placeholder', 'Otto is working…')
  expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
  await userEvent.type(box(), 'also this{Enter}')
  expect(calls).toEqual([])

  await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
  await waitFor(() => expect(calls).toEqual([{ path: 'stop', body: null }]))
})

it('between turns: a follow-up posts the text and clears the box', async () => {
  const { calls, onSent } = setup()
  expect(box()).toHaveAttribute('placeholder', 'Reply to Otto…')
  expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  await userEvent.type(box(), 'also add a test for exactly 11 units{Enter}')
  await waitFor(() => expect(calls).toEqual([{ path: 'messages', body: { text: 'also add a test for exactly 11 units' } }]))
  expect(onSent).toHaveBeenCalledWith('also add a test for exactly 11 units', null)
  expect(box()).toHaveValue('')
})

it('the chat keeps its model: a label, not a picker', async () => {
  setup()
  expect(await screen.findByText('GPT-4.1 mini')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /GPT-4.1 mini/ })).not.toBeInTheDocument()
})

it('a plain chat can take a repo in a follow-up', async () => {
  const { calls } = setup({ repo: null })
  await userEvent.type(box(), '@petal')
  await userEvent.keyboard('{Enter}')
  await userEvent.type(box(), 'fix it{Enter}')
  await waitFor(() => expect(calls[0]?.body).toEqual({ text: 'fix it', repo: 'Taufik041/petal' }))
})

it('a 409 is shown inline', async () => {
  setup({ repo: 'Taufik041/otto_test' }, () => HttpResponse.json({ detail: 'Start a new chat for a different repo.' }, { status: 409 }))
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByText("That message didn't go.")).toBeInTheDocument()
  expect(screen.getByText('Start a new chat for a different repo.')).toBeInTheDocument()
})

it('a 409 because Otto is still working says so plainly', async () => {
  setup({}, () => HttpResponse.json({ detail: 'session s1 is running; wait until it finishes' }, { status: 409 }))
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByText('Otto is still working on this chat. Wait until it finishes, or stop it.')).toBeInTheDocument()
})

it('a 429 cap is shown inline', async () => {
  setup({}, () => HttpResponse.json({ code: 'daily_limit', used: 50000, limit: 50000, resets_at: 'x' }, { status: 429 }))
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByText("You've used today's limit.")).toBeInTheDocument()
})
