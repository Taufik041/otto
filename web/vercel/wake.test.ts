// @vitest-environment node
import { handleWake, MIN_OPEN_MS, resetLimits, wakeEmail } from './wake.mjs'

const ORIGIN = 'https://otto.taufi.dev'
const NOW = Date.parse('2026-10-08T18:45:00Z')
const ENV = { RESEND_API_KEY: 're_test', OTTO_NOTIFY_TO: 'taufik@example.com', EMAIL_FROM: 'Otto <noreply@taufi.dev>' }

type Sent = { from: string; to: string[]; reply_to?: string; subject: string; text: string; html: string }

function request(body: unknown, { origin = ORIGIN, type = 'application/json', method = 'POST', raw }: {
  origin?: string | null; type?: string; method?: string; raw?: string
} = {}) {
  const headers: Record<string, string> = { 'content-type': type, 'user-agent': 'Mozilla/5.0 <test>' }
  if (origin) headers.origin = origin
  return new Request(`${ORIGIN}/api/wake`, { method, headers, body: method === 'GET' ? undefined : raw ?? JSON.stringify(body) })
}

const good = (over: Record<string, unknown> = {}) => ({
  email: 'visitor@example.com',
  message: "Hi Taufik, I'd like to try Otto. Could you bring it up?",
  page: '/',
  openedAt: NOW - 10_000,
  website: '',
  ...over,
})

async function call(req: Request, { env = ENV, ip = '203.0.113.7', fail = false } = {}) {
  const sent: Sent[] = []
  const send = async (payload: Sent) => {
    sent.push(payload)
    if (fail) throw new Error('resend said no')
  }
  const res = await handleWake(req, { env, send, now: NOW, ip })
  return { res, body: await res.json(), sent }
}

beforeEach(() => resetLimits())

describe('POST /api/wake', () => {
  it('sends one email to Taufik, with the visitor as reply_to, and never to the visitor', async () => {
    const { res, body, sent } = await call(request(good()))
    expect(res.status).toBe(200)
    expect(body).toEqual({ ok: true })
    expect(sent).toHaveLength(1)
    const [msg] = sent
    expect(msg!.to).toEqual(['taufik@example.com'])
    expect(msg!.to).not.toContain('visitor@example.com')
    expect(msg!.reply_to).toBe('visitor@example.com')
    expect(msg!.from).toBe('Otto <noreply@taufi.dev>')
    expect(msg!.subject).toBe('Someone wants to try Otto')
    expect(msg!.text).toContain('visitor@example.com')
    expect(msg!.text).toContain('2026-10-08 18:45 UTC')
    expect(msg!.text).toContain('2026-10-09 00:15 IST')
    expect(msg!.text).toContain('Mozilla/5.0 <test>')
    expect(res.headers.get('cache-control')).toBe('no-store')
  })

  it.each([
    ['a line break (header injection)', 'visitor@example.com\r\nBcc: everyone@example.com'],
    ['a bare newline', 'visitor@example.com\nx'],
    ['a list', 'a@example.com, b@example.com'],
    ['a display name', 'Visitor <visitor@example.com>'],
    ['not an address', 'visitor'],
    ['too long', `${'a'.repeat(250)}@example.com`],
    ['not a string', 42],
  ])('rejects %s, and sends nothing', async (_, email) => {
    const { res, body, sent } = await call(request(good({ email })))
    expect(res.status).toBe(422)
    expect(body.error).toBe('invalid_email')
    expect(sent).toEqual([])
  })

  it('a filled honeypot looks like success, and sends nothing', async () => {
    const { res, body, sent } = await call(request(good({ website: 'https://spam.example' })))
    expect(res.status).toBe(200)
    expect(body).toEqual({ ok: true })
    expect(sent).toEqual([])
  })

  it.each([
    ['under 3 seconds after the form opened', NOW - MIN_OPEN_MS + 1],
    ['a time in the future', NOW + 60_000],
    ['no time at all', undefined],
  ])('rejects %s', async (_, openedAt) => {
    const { res, body, sent } = await call(request(good({ openedAt })))
    expect(res.status).toBe(400)
    expect(body.error).toBe('too_fast')
    expect(sent).toEqual([])
  })

  it('caps the message at 1000 characters', async () => {
    expect((await call(request(good({ message: 'x'.repeat(1000) })))).res.status).toBe(200)
    resetLimits()
    const { res, body } = await call(request(good({ message: 'x'.repeat(1001) })))
    expect(res.status).toBe(422)
    expect(body.error).toBe('invalid_message')
  })

  it.each([
    ['another site', 'https://evil.example'],
    ['no Origin header', null],
  ])('same origin only: %s is 403', async (_, origin) => {
    const { res, sent } = await call(request(good(), { origin }))
    expect(res.status).toBe(403)
    expect(sent).toEqual([])
  })

  it('JSON only', async () => {
    expect((await call(request(null, { type: 'application/x-www-form-urlencoded', raw: 'email=a@b.co' }))).res.status).toBe(415)
    expect((await call(request(null, { raw: '{not json' }))).res.status).toBe(400)
    expect((await call(request(null, { raw: '[1,2]' }))).res.status).toBe(400)
    expect((await call(request(null, { raw: JSON.stringify(good({ message: 'x'.repeat(9000) })) }))).res.status).toBe(413)
  })

  it('POST only', async () => {
    expect((await call(request(null, { method: 'GET' }))).res.status).toBe(405)
  })

  it('a best-effort limit per IP: 3 an hour', async () => {
    for (let i = 0; i < 3; i++) expect((await call(request(good()))).res.status).toBe(200)
    const { res, body, sent } = await call(request(good()))
    expect(res.status).toBe(429)
    expect(body.error).toBe('rate_limited')
    expect(Number(res.headers.get('retry-after'))).toBeGreaterThan(0)
    expect(sent).toEqual([])
    expect((await call(request(good()), { ip: '198.51.100.1' })).res.status).toBe(200) // another visitor
  })

  it.each([
    ['no key', { ...ENV, RESEND_API_KEY: '' }],
    ['no inbox', { ...ENV, OTTO_NOTIFY_TO: '' }],
  ])('unconfigured (%s): 503, with the mailto fallback', async (_, env) => {
    const { res, body, sent } = await call(request(good()), { env })
    expect(res.status).toBe(503)
    expect(body).toMatchObject({ error: 'email_unavailable', fallback: 'mailto:hello@taufi.dev' })
    expect(sent).toEqual([])
  })

  it('Resend failing is 502, and the try is given back', async () => {
    const { res, body } = await call(request(good()), { fail: true })
    expect(res.status).toBe(502)
    expect(body.error).toBe('email_failed')
    for (let i = 0; i < 3; i++) expect((await call(request(good()))).res.status).toBe(200)
  })

  it('EMAIL_FROM defaults to Otto <noreply@taufi.dev>', async () => {
    const { sent } = await call(request(good()), { env: { ...ENV, EMAIL_FROM: '' } })
    expect(sent[0]!.from).toBe('Otto <noreply@taufi.dev>')
  })
})

describe('the email', () => {
  it('escapes everything in the HTML', () => {
    const { html, text } = wakeEmail({
      email: 'visitor@example.com', message: '<img src=x onerror=alert(1)> & "hi"', page: '/<b>', userAgent: '<ua>', now: NOW,
    })
    expect(html).not.toMatch(/<img|<b>|<ua>/)
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt; &amp; &quot;hi&quot;')
    expect(text).toContain('<img src=x onerror=alert(1)> & "hi"') // the text part is plain text
  })
})
