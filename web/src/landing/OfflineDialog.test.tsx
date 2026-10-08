import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { DEFAULT_MESSAGE, OfflineDialog } from './OfflineDialog'

function wake(answer: () => Response) {
  const posted: Record<string, unknown>[] = []
  server.use(
    http.post('*/api/wake', async ({ request }) => {
      posted.push((await request.json()) as Record<string, unknown>)
      return answer()
    }),
  )
  return posted
}

function open(bookingUrl: string | null = null) {
  const onClose = vi.fn()
  const onWatch = vi.fn()
  render(<OfflineDialog mobile={false} bookingUrl={bookingUrl} onClose={onClose} onWatch={onWatch} />)
  return { onClose, onWatch, dialog: () => screen.getByRole('dialog') }
}

const toForm = () => userEvent.click(screen.getByRole('button', { name: 'Bring it back up' }))

describe('the offline dialog', () => {
  it('says why, offers to bring it up, and the links', async () => {
    const { onClose, onWatch } = open()
    const d = screen.getByRole('dialog', { name: 'Otto is offline right now.' })
    expect(within(d).getByText(
      "Otto is a free beta that runs on Taufik's own hardware, so it sleeps when he's away. Ask him to bring it up, or book a time and he'll show it to you live.",
    )).toBeInTheDocument()
    expect(within(d).queryByRole('link', { name: 'Book a live demo' })).not.toBeInTheDocument() // no booking URL
    await userEvent.click(within(d).getByRole('link', { name: 'Watch the demo' }))
    expect(onWatch).toHaveBeenCalled()
    await userEvent.click(within(d).getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('"Book a live demo" opens the booking page in a new tab', () => {
    open('https://cal.example/taufik/otto')
    const book = screen.getByRole('link', { name: 'Book a live demo' })
    expect(book).toHaveAttribute('href', 'https://cal.example/taufik/otto')
    expect(book).toHaveAttribute('target', '_blank')
    expect(book.getAttribute('rel')).toContain('noopener')
  })

  it('the form: email and a prefilled message; Send → "Sent. Taufik will reply to you at …"', async () => {
    const posted = wake(() => HttpResponse.json({ ok: true }))
    open()
    await toForm()
    expect(screen.getByRole('dialog', { name: 'Bring Otto back up' })).toBeInTheDocument()
    expect(screen.getByLabelText('Message')).toHaveValue(DEFAULT_MESSAGE)
    expect(DEFAULT_MESSAGE).toBe("Hi Taufik, I'd like to try Otto. Could you bring it up?")
    await userEvent.type(screen.getByLabelText('Your email'), 'visitor@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('dialog', { name: 'Sent.' })).toBeInTheDocument()
    expect(screen.getByText('Taufik will reply to you at visitor@example.com.')).toBeInTheDocument()
    expect(posted).toHaveLength(1)
    expect(posted[0]).toMatchObject({ email: 'visitor@example.com', message: DEFAULT_MESSAGE, website: '', page: '/' })
    expect(typeof posted[0]!.openedAt).toBe('number')
  })

  it('a bad email is an inline error, and nothing is sent', async () => {
    const posted = wake(() => HttpResponse.json({ ok: true }))
    open()
    await toForm()
    await userEvent.type(screen.getByLabelText('Your email'), 'visitor@')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByText('Enter a valid email.')).toBeInTheDocument()
    expect(posted).toEqual([])
  })

  it('the message is capped at 1000 characters', async () => {
    open()
    await toForm()
    expect(screen.getByLabelText('Message')).toHaveAttribute('maxLength', '1000')
  })

  it('the honeypot is there for bots, hidden from people and screen readers', async () => {
    open()
    await toForm()
    const trap = document.querySelector('input[name="website"]')!
    expect(trap).toHaveAttribute('tabindex', '-1')
    expect(trap).toHaveAttribute('aria-hidden', 'true')
    expect(trap).toHaveValue('')
  })

  it('sent too soon: asked to wait a few seconds', async () => {
    wake(() => HttpResponse.json({ error: 'too_fast' }, { status: 400 }))
    open()
    await toForm()
    await userEvent.type(screen.getByLabelText('Your email'), 'visitor@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Give it a few seconds, then send again.')).toBeInTheDocument()
  })

  it('rate-limited: says so, with an email link', async () => {
    wake(() => HttpResponse.json({ error: 'rate_limited' }, { status: 429 }))
    open()
    await toForm()
    await userEvent.type(screen.getByLabelText('Your email'), 'visitor@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText(/a few requests from here already/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'email hello@taufi.dev' }).getAttribute('href')).toMatch(/^mailto:hello@taufi\.dev\?/)
  })

  it.each([
    ['email not set up (503)', () => HttpResponse.json({ error: 'email_unavailable', fallback: 'mailto:hello@taufi.dev' }, { status: 503 })],
    ['the function unreachable', () => HttpResponse.error()],
  ])('%s: falls back to a mailto: carrying the message', async (_, answer) => {
    wake(answer)
    open()
    await toForm()
    await userEvent.type(screen.getByLabelText('Your email'), 'visitor@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    const link = await screen.findByRole('link', { name: 'Email hello@taufi.dev' })
    const href = link.getAttribute('href')!
    expect(href.startsWith('mailto:hello@taufi.dev?')).toBe(true)
    expect(decodeURIComponent(href)).toContain(DEFAULT_MESSAGE)
    expect(decodeURIComponent(href)).toContain('Reply to: visitor@example.com')
  })

  it('Escape closes it', async () => {
    const { onClose } = open()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
