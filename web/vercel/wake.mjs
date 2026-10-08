// POST /api/wake: the landing page's "Bring it back up" form. It runs on Vercel (in the landing
// project), not on Otto's server, so it works while the API is down. It emails Taufik once,
// through Resend, with the visitor as reply_to; it never sends anything to the visitor.
//
// handleWake(request, { env, send, now, ip }) takes a web Request and returns a Response:
//   vercel/functions/wake.mjs     the Vercel function (Node), sending through Resend
//   vite.landing.config.ts        dev and preview: the same handler, logging the email instead
//
// Abuse controls: same origin only, JSON only, a size cap, a honeypot field ("website"), at
// least MIN_OPEN_MS between opening the form and sending it, strict validation and length caps,
// and a best-effort limit per IP (in this instance's memory).

export const MIN_OPEN_MS = 3_000
export const MAX_MESSAGE = 1_000
const MAX_BODY = 4_096
const LIMIT = { count: 3, windowMs: 3_600_000 } // per IP
const FALLBACK = 'mailto:hello@taufi.dev'
const DEFAULT_FROM = 'Otto <noreply@taufi.dev>'
const RESEND_URL = 'https://api.resend.com/emails'
// one plain address: no display name, no list, no whitespace or line breaks (header injection)
const ADDRESS = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/

const hits = new Map() // ip -> times (ms) within the window

export function resetLimits() {
  hits.clear()
}

function take(ip, now) {
  const recent = (hits.get(ip) ?? []).filter((t) => t > now - LIMIT.windowMs)
  if (recent.length >= LIMIT.count) return Math.ceil((recent[0] + LIMIT.windowMs - now) / 1000)
  recent.push(now)
  hits.set(ip, recent)
  if (hits.size > 5_000) for (const [k, v] of hits) if (v.every((t) => t <= now - LIMIT.windowMs)) hits.delete(k)
  return 0
}

function giveBack(ip) {
  hits.get(ip)?.pop()
}

export function singleAddress(value) {
  return typeof value === 'string' && value.length <= 254 && ADDRESS.test(value) ? value : null
}

export const escapeHtml = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const pad = (n) => String(n).padStart(2, '0')
function stamp(ms, offsetMinutes, zone) {
  const d = new Date(ms + offsetMinutes * 60_000)
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} ${zone}`
}

/** { subject, text, html } asking Taufik to bring Otto up (the gateway's shared/email.py sends the same). */
export function wakeEmail({ email, message, page, userAgent, now }) {
  const fields = [
    ['From', email],
    ['Message', message || '(none)'],
    ['Time', `${stamp(now, 0, 'UTC')} (${stamp(now, 330, 'IST')})`],
    ['Page', page || '/'],
    ['User agent', userAgent || '(unknown)'],
  ]
  const text = 'Someone asked to bring Otto back up.\n\n' + fields.map(([k, v]) => `${k}: ${v}\n`).join('')
  const paras = ['Someone asked to bring Otto back up.', ...fields.map(([k, v]) => `<strong>${k}</strong><br>${escapeHtml(v).replace(/\n/g, '<br>')}`)]
  const html =
    '<div style="font-family:-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#15171C">' +
    paras.map((p) => `<p style="margin:0 0 12px">${p}</p>`).join('') +
    '</div>'
  return { subject: 'Someone wants to try Otto', text, html }
}

/** Send one email through Resend's HTTP API (throws when Resend refuses). */
export async function resendSend(payload, apiKey, fetchFn = fetch) {
  const res = await fetchFn(RESEND_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  })
  if (!res.ok) throw new Error(`Resend refused the email (${res.status})`)
}

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers } })

/**
 * The handler. env: { RESEND_API_KEY, OTTO_NOTIFY_TO, EMAIL_FROM }; send(payload): delivers the
 * email (Resend, or a log in dev); now: ms; ip: the client's address.
 */
export async function handleWake(request, { env, send, now = Date.now(), ip = 'unknown' }) {
  if (request.method !== 'POST') return json(405, { error: 'method_not_allowed' }, { Allow: 'POST' })

  // same origin only: the landing page's own form
  const origin = request.headers.get('origin')
  const site = request.headers.get('sec-fetch-site')
  if (!origin || origin !== new URL(request.url).origin || (site && site !== 'same-origin'))
    return json(403, { error: 'forbidden' })
  if (!(request.headers.get('content-type') ?? '').toLowerCase().startsWith('application/json'))
    return json(415, { error: 'json_only' })

  const raw = await request.text()
  if (raw.length > MAX_BODY) return json(413, { error: 'too_large' })
  let body
  try {
    body = JSON.parse(raw)
  } catch {
    return json(400, { error: 'bad_json' })
  }
  if (!body || typeof body !== 'object' || Array.isArray(body)) return json(400, { error: 'bad_json' })

  // a bot that filled the hidden field: tell it all went well
  if (typeof body.website === 'string' && body.website.trim() !== '') return json(200, { ok: true })
  const opened = Number(body.openedAt)
  if (!Number.isFinite(opened) || opened > now || now - opened < MIN_OPEN_MS) return json(400, { error: 'too_fast' })

  const email = singleAddress(typeof body.email === 'string' ? body.email.trim() : body.email)
  if (!email) return json(422, { error: 'invalid_email' })
  const message = body.message ?? ''
  if (typeof message !== 'string' || message.length > MAX_MESSAGE) return json(422, { error: 'invalid_message' })
  const page = typeof body.page === 'string' ? body.page.slice(0, 200) : '/'

  if (!env.RESEND_API_KEY || !singleAddress(env.OTTO_NOTIFY_TO ?? ''))
    return json(503, { error: 'email_unavailable', fallback: FALLBACK })

  const wait = take(ip, now)
  if (wait) return json(429, { error: 'rate_limited' }, { 'Retry-After': String(wait) })

  const { subject, text, html } = wakeEmail({
    email, message: message.trim(), page, userAgent: (request.headers.get('user-agent') ?? '').slice(0, 300), now,
  })
  try {
    // to: Taufik only. The visitor is the reply_to, so a reply reaches them; nothing is sent to them
    await send({ from: env.EMAIL_FROM || DEFAULT_FROM, to: [env.OTTO_NOTIFY_TO], reply_to: email, subject, text, html })
  } catch (e) {
    giveBack(ip)
    console.error(`[wake] the email didn't go: ${e instanceof Error ? e.message : e}`)
    return json(502, { error: 'email_failed', fallback: FALLBACK })
  }
  return json(200, { ok: true })
}

/** Dev and preview: log the email instead of sending it (vite.landing.config.ts). */
export const logEmail = async (payload) => {
  console.log(
    `\n[wake] not sent (local dev)\n  to: ${payload.to.join(', ')}\n  reply-to: ${payload.reply_to}\n  subject: ${payload.subject}\n` +
      payload.text.split('\n').map((l) => `  | ${l}`).join('\n'),
  )
}
