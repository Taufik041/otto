import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Composer, type Reply } from './Composer'
import { models, repos } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'

function setup(reply: Partial<Reply> = {}, follow?: () => Response) {
  const calls: { path: string; body: unknown }[] = []
  const ids: unknown[] = [] // each post's client_message_id
  server.use(
    http.get(`${API}/models`, () => HttpResponse.json({ default_model: 'openrouter:openrouter/free', models })),
    http.get(`${API}/repos`, () => HttpResponse.json(repos)),
    http.post(`${API}/sessions/s1/messages`, async ({ request }) => {
      const { client_message_id, ...body } = (await request.json()) as Record<string, unknown>
      ids.push(client_message_id)
      calls.push({ path: 'messages', body })
      return follow?.() ?? HttpResponse.json({ id: 's1', status: 'queued', repo: null }, { status: 202 })
    }),
    http.post(`${API}/sessions/s1/stop`, () => {
      calls.push({ path: 'stop', body: null })
      return HttpResponse.json({ id: 's1', status: 'stopped' })
    }),
  )
  const onSending = vi.fn()
  const onSendFailed = vi.fn()
  renderSignedIn(
    <Composer
      mobile={false}
      hero={false}
      reply={{ sessionId: 's1', live: false, model: 'openai:gpt-4.1-mini', repo: 'Taufik041/otto_test', onSending, onSendFailed, ...reply }}
    />,
  )
  return { calls, ids, onSending, onSendFailed }
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
  const { calls, ids, onSending } = setup()
  expect(box()).toHaveAttribute('placeholder', 'Reply to Otto…')
  expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  await userEvent.type(box(), 'also add a test for exactly 11 units{Enter}')
  await waitFor(() => expect(calls).toEqual([{ path: 'messages', body: { text: 'also add a test for exactly 11 units' } }]))
  // shown at once, under the id the gateway gets with it
  expect(onSending).toHaveBeenCalledWith({ id: ids[0], text: 'also add a test for exactly 11 units', repo: null })
  expect(ids[0]).toMatch(/^[\w-]{8,64}$/)
  expect(box()).toHaveValue('')
})

it('the picker starts on the chat\'s model, and a new choice goes with the next message', async () => {
  const { calls } = setup()
  const picker = await screen.findByRole('button', { name: /GPT-4.1 mini/ })
  expect(picker).toBeEnabled()
  await userEvent.click(picker)
  await userEvent.click(screen.getByRole('option', { name: /OpenRouter Free/ }))
  expect(screen.getByRole('button', { name: /OpenRouter Free/ })).toBeInTheDocument()
  await userEvent.type(box(), 'try the free one{Enter}')
  await waitFor(() =>
    expect(calls).toEqual([{ path: 'messages', body: { text: 'try the free one', model: 'openrouter:openrouter/free' } }]),
  )
})

it('the same model is not sent again', async () => {
  const { calls } = setup()
  await screen.findByRole('button', { name: /GPT-4.1 mini/ })
  await userEvent.type(box(), 'more{Enter}')
  await waitFor(() => expect(calls).toEqual([{ path: 'messages', body: { text: 'more' } }]))
})

it('the picker is disabled while Otto works', async () => {
  setup({ live: true })
  expect(await screen.findByRole('button', { name: /GPT-4.1 mini/ })).toBeDisabled()
})

it('an unavailable model (400) is shown inline', async () => {
  setup({}, () =>
    HttpResponse.json(
      { detail: [{ type: 'value_error', loc: ['body', 'model'], msg: "Value error, unknown or unavailable model 'x'; see GET /models" }] },
      { status: 400 },
    ),
  )
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByText('Pick another model.')).toBeInTheDocument()
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

it('bus_unavailable (the gateway lost RabbitMQ) says Otto is restarting, not a raw error', async () => {
  const detail = "Otto can't reach its message queue right now. Try again in a minute."
  setup({}, () => HttpResponse.json({ error: 'bus_unavailable', detail }, { status: 503 }))
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('Otto is restarting. Try again in a minute.')
  expect(screen.queryByText(detail)).not.toBeInTheDocument()
  expect(screen.queryByText(/model isn.t available/)).not.toBeInTheDocument()
})

it('a 429 cap is shown inline', async () => {
  setup({}, () => HttpResponse.json({ code: 'daily_limit', used: 50000, limit: 50000, resets_at: 'x' }, { status: 429 }))
  await userEvent.type(box(), 'x{Enter}')
  expect(await screen.findByText("You've used today's limit.")).toBeInTheDocument()
})

it('workers offline: a repo chat can\'t take a follow-up, and says why', async () => {
  server.use(http.get(`${API}/health`, () => HttpResponse.json({ status: 'up', workers: 'offline', version: 't' })))
  const { calls } = setup()
  expect(await screen.findByText("Otto's workers are offline right now. Plain chat still works.")).toBeInTheDocument()
  await userEvent.type(box(), 'and the docs{Enter}')
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  expect(calls).toEqual([])
})

it('workers offline: a plain chat still takes a follow-up', async () => {
  server.use(http.get(`${API}/health`, () => HttpResponse.json({ status: 'up', workers: 'offline', version: 't' })))
  const { calls } = setup({ repo: null })
  await screen.findByText("Otto's workers are offline right now. Plain chat still works.")
  await userEvent.type(box(), 'and in Python?{Enter}')
  await waitFor(() => expect(calls.map((c) => c.path)).toEqual(['messages']))
})

it('a follow-up that fails is taken back out of the chat, and the next try gets a new id', async () => {
  let fail = true
  const { calls, ids, onSending, onSendFailed } = setup({}, () =>
    fail
      ? HttpResponse.json({ detail: 'session s1 is running; wait until it finishes' }, { status: 409 })
      : HttpResponse.json({ id: 's1', status: 'queued', repo: null }, { status: 202 }),
  )
  await userEvent.type(box(), 'more{Enter}')
  await waitFor(() => expect(onSendFailed).toHaveBeenCalledWith(ids[0]))
  expect(box()).toHaveValue('more') // kept, to send again
  fail = false
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  await waitFor(() => expect(calls).toHaveLength(2))
  expect(ids[1]).not.toBe(ids[0])
  expect(onSending).toHaveBeenCalledTimes(2)
})
