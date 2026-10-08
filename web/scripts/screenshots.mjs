// Screenshots of the main screens at 1440px and 390px, light and dark, to compare with the design
// mockup (docs/design/Otto v4.dc.html). The API is mocked with the design brief's sample data, so
// no gateway is needed; the dev server must be running (npm run dev).
//
//   node scripts/screenshots.mjs [out-dir]        (default: screenshots/)
//   LAUNCH=1 node scripts/screenshots.mjs screenshots/launch    (the chat states the launch needs)
//   AUTH=1 node scripts/screenshots.mjs screenshots/auth        (sign-in, legal, 404, request access)
//
// The workspace state also checks that the chat header and the panel header line up.
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'
import {
  BRANCH, COMMIT_OUT, FAILING, FIX_DIFF, INTRO, MODELS as models, PASSING, PLAIN_REPLY, PR_TITLE, PRICING_MD, PUSH_OUT, REPLY,
  SEARCH_OUT, TASK, TEST_DIFF,
} from '../src/fixtures/session.js'

const APP = process.env.APP_URL || 'http://localhost:5173'
const API = process.env.VITE_API_URL || 'http://localhost:8000'
const OUT = process.argv[2] || 'screenshots'
mkdirSync(OUT, { recursive: true })

const ago = (h) => new Date(Date.now() - h * 3600_000).toISOString()
const user = (over = {}) => ({
  id: 'u1', email: 'taufik@hey.com', name: 'Taufik Khan', github_login: 'Taufik041', avatar_url: null,
  default_model: null, daily_token_limit: 50000, has_password: true, created_at: '2026-09-01T10:00:00+00:00', ...over,
})
const repos = [
  ['otto_test', true, 2], ['portfolio', false, 72], ['petal', true, 170],
].map(([n, p, h]) => ({ full_name: `Taufik041/${n}`, private: p, updated_at: ago(h), default_branch: 'main', installation_id: 1 }))
// the sidebar's dots: working, and unseen ends (s3 was seen; s4 is a plain chat at rest)
const ATTENTION = { s1: 'done', s2: 'working', s5: 'failed' }
const sessions = [
  ['s1', 'Fix failing pricing tests', 'done', 'Taufik041/otto_test', 1],
  ['s2', 'Portfolio contact form', 'running', 'Taufik041/portfolio', 2],
  ['s3', 'Add line_count() to Order', 'done', 'Taufik041/otto_test', 26],
  ['s4', 'Explain the catalog module', 'done', null, 80],
  ['s5', 'Refactor shipping fees', 'failed', 'Taufik041/otto_test', 300],
].map(([id, title, status, repo, h]) => ({ id, title, status, repo, model: models.default_model, pr_url: null,
    updated_at: ago(h), attention: ATTENTION[id] ?? null }))
const DAILY = [8.2, 14.1, 6.3, 0, 3.4, 18.9, 22.4, 11.2, 9.8, 16.5, 4.1, 0, 7.7, 12.4]
const usage = {
  today: { tokens: 12400, limit: 50000, resets_at: '2026-10-02T00:00:00+00:00' },
  month: { sessions: 38, tokens: 412000, est_cost_usd: 0 },
  daily: DAILY.map((v, i) => ({ date: new Date(Date.now() - (13 - i) * 86400_000).toISOString().slice(0, 10), tokens: Math.round(v * 1000) })),
  by_model: [{ model: 'openrouter:openrouter/free', tokens: 388000, est_cost_usd: 0 }, { model: 'openai:gpt-4.1-mini', tokens: 24000, est_cost_usd: 0 }],
}

// --- a chat, as the events the backend writes (the design brief's sample run) -------------------
function events(scene) {
  const out = []
  let seq = 0
  let t = Date.now() - 3 * 60_000
  const add = (type, payload = {}) => out.push({ seq: ++seq, ts: new Date((t += 2000)).toISOString(), type, payload })
  let n = 0
  const ok = (extra = {}) => ({ exit_code: 0, stdout: '', stderr: '', ...extra })
  const act = (kind, args, result = ok()) => {
    const id = `a${++n}`
    add('bus.action', { action_id: id, kind, payload: args })
    if (result) add('bus.result', { action_id: id, ok: true, payload: result })
  }
  const plain = scene === 'plain'
  const task = plain ? 'Can you add a discount for orders over $500?' : TASK
  add('session.created', { task, repo: plain ? null : 'Taufik041/otto_test',
    model: scene === 'errCredit' ? 'openai:gpt-4.1-mini' : 'openrouter:openrouter/free' })
  add('session.status', { status: 'running' })
  add('llm.message', { message: { role: 'user', content: task } })
  if (plain) {
    add('llm.message', { message: { role: 'assistant', content: PLAIN_REPLY } })
    add('session.status', { status: 'done' })
    return out
  }
  if (scene === 'errSetup') {
    add('error', { stage: 'create_sandbox', message: 'ApiException: (500)' })
    add('session.status', { status: 'failed' })
    return out
  }
  if (scene === 'limit') {
    add('usage.limit_reached', { used: 50000, limit: 50000, resets_at: '2026-10-03T00:00:00+00:00' })
    add('session.status', { status: 'limited' })
    return out
  }
  add('llm.message', { message: { role: 'assistant', content: INTRO, tool_calls: [{ id: 'c' }] } })
  act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 1, stdout: FAILING, stderr: '' })
  act('code.search', { pattern: 'qualifies_for_bulk' }, ok({ stdout: SEARCH_OUT }))
  act('fs.read', { path: 'docs/PRICING.md', start_line: 1, end_line: 12 }, ok({ stdout: PRICING_MD }))
  if (scene === 'working') {
    act('fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, null)
    return out
  }
  if (scene === 'error') {
    add('error', { stage: 'llm', message: 'no usable LLM response after 6 attempts; last: rate limited' })
    add('session.status', { status: 'failed' })
    return out
  }
  if (scene === 'errCredit') {
    add('error', { stage: 'model', reason: 'quota', provider: 'openai', model: 'openai:gpt-4.1-mini', message: 'openai is unusable: quota' })
    add('session.status', { status: 'failed' })
    return out
  }
  act('fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, ok({ added: 1, removed: 1, diff: FIX_DIFF }))
  act('shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: PASSING }))
  act('git.commit', { message: PR_TITLE }, ok({ stdout: COMMIT_OUT }))
  if (scene === 'errPush') {
    act('git.push', {}, { exit_code: 1, stdout: '', stderr: 'rejected' })
    add('error', { stage: 'finish', step: 'git.push', message: 'git.push: rejected' })
    add('session.status', { status: 'failed' })
    return out
  }
  act('git.push', {}, ok({ stderr: PUSH_OUT, branch: BRANCH, base: 'main', diffstat: { files: 1, additions: 1, deletions: 1 } }))
  add('llm.message', { message: { role: 'assistant', content: REPLY + ' Review the change, then create the pull request.' } })
  // the finish proposes the PR; the user opens it ("Create pull request") or not
  add('pr.proposed', { title: PR_TITLE, body: REPLY, head: BRANCH, base: 'main',
    additions: 1, deletions: 1, files: 1, tests: { passed: 9, failed: 0, text: '9 passed' } })
  add('session.status', { status: 'done' })
  if (scene === 'proposal' || scene === 'creating' || scene === 'prError') return out
  if (scene === 'modelSwitch') {
    add('session.status', { status: 'provisioning' })
    add('session.model_changed', { from: 'openrouter:openrouter/free', to: 'openai:gpt-4.1-mini' })
    add('llm.message', { message: { role: 'user', content: 'explain the fix in one sentence' } })
    add('session.status', { status: 'running' })
    add('llm.message', { message: { role: 'assistant', content: 'Ten units should qualify, but the check used `>` so only eleven or more did; `>=` fixes it.' } })
    add('session.status', { status: 'done' })
    return out
  }
  if (scene === 'declined') {
    add('pr.declined', {})
    return out
  }
  add('pr.opened', { number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3' })
  if (scene === 'followup') {
    add('session.status', { status: 'provisioning' })
    add('sandbox.reused', {})
    add('session.status', { status: 'running' })
    add('llm.message', { message: { role: 'user', content: 'also add a test for exactly 11 units' } })
    act('fs.replace', { path: 'tests/test_pricing.py', old_str: 'a', new_str: 'b' }, ok({ added: 3, removed: 0, diff: TEST_DIFF }))
    act('shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: '..........                               [100%]\n10 passed in 0.10s' }))
    act('git.commit', { message: 'Add test for 11-unit orders' })
    act('git.push', {}, ok({ branch: 'otto/4299fa2c3f', base: 'main', diffstat: { files: 2, additions: 4, deletions: 1 } }))
    add('llm.message', { message: { role: 'assistant', content: 'Added a test for exactly 11 units. All 10 tests pass, and the commit is on the same pull request, #3.' } })
    add('pr.updated', { number: 3, url: 'https://github.com/Taufik041/otto_test/pull/3', additions: 4, deletions: 1, files: 2 })
    add('session.status', { status: 'done' })
  }
  return out
}

/** Answer the gateway's routes; `signedIn: false` refuses the refresh cookie. */
async function mockApi(page, { signedIn = true, me = user(), github = true, chat = 'done', workers = 'online', refuse = 'invite' } = {}) {
  await page.routeWebSocket(/\/sessions\/s1\/ws/, () => {}) // connected and quiet: the stored events are the chat
  const json = (route, body, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body),
      headers: { 'access-control-allow-origin': APP, 'access-control-allow-credentials': 'true' } })
  await page.route(`${API}/**`, (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    if (req.method() === 'OPTIONS')
      return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': APP, 'access-control-allow-credentials': 'true',
        'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } })
    if (path === '/auth/refresh')
      return signedIn ? json(route, { access_token: 't', token_type: 'bearer', expires_in: 900, user: me }) : json(route, { detail: 'sign in again' }, 401)
    if (path === '/auth/login') return json(route, { detail: 'wrong email or password' }, 401)
    // email first: taufik@hey.com has an account; anyone else is new, and the sign-up is refused
    if (path === '/auth/email-status') return json(route, { exists: /taufik@hey\.com/i.test(req.postData() ?? '') })
    if (path === '/auth/signup')
      return refuse === 'paused'
        ? json(route, { error: 'paused', detail: "Otto isn't taking new accounts right now." }, 503)
        : json(route, { error: 'invite_only', detail: 'Otto is invite-only right now.' }, 403)
    if (path === '/auth/forgot') return json(route, { ok: true })
    if (path === '/access-requests') return json(route, { ok: true }, 201)
    if (path === '/wake-requests') return json(route, { ok: true }, 202)
    if (path === '/health') return json(route, { status: 'up', workers, version: 'screenshots' })
    if (path === '/models') return json(route, models)
    if (path === '/sessions/s1/pr' && chat === 'creating') return // never answers: the card stays "Creating…"
    if (path === '/sessions/s1/pr' && chat === 'prError')
      return json(route, { detail: "GitHub didn't open the pull request: Validation Failed" }, 502)
    if (path === '/sessions/s1/seen') return json(route, { last_seen_seq: 0 })
    if (path === '/repos') return json(route, github ? repos : [])
    if (path === '/github')
      return json(route, { connected: github, login: me.github_login, avatar_url: null, installations: github ? [{ id: 1, account_login: 'Taufik041' }] : [] })
    if (path === '/sessions') return json(route, sessions)
    if (path === '/sessions/s1/events') return json(route, events(chat))
    if (path === '/sessions/s1/ws-ticket') return json(route, { ticket: 't' })
    if (path === '/sessions/s1') {
      const plain = chat === 'plain'
      return json(route, { ...sessions[0], id: 's1', title: plain ? 'Discount for large orders' : 'Fix bulk discount threshold',
        status: chat === 'working' ? 'running' : sessions[0].status,
        model: chat === 'modelSwitch' || chat === 'errCredit' ? 'openai:gpt-4.1-mini' : models.default_model,
        repo: plain ? null : 'Taufik041/otto_test', task: '', repo_url: null, work_branch: plain ? null : 'otto/4299fa2c3f', created_at: ago(1) })
    }
    if (path === '/usage') return json(route, usage)
    return json(route, { detail: 'not mocked' }, 404)
  })
}

const browser = await chromium.launch()

async function shot(name, { width, theme, path, setup, api, before }) {
  const page = await browser.newPage({ viewport: { width, height: width > 500 ? 900 : 844 }, deviceScaleFactor: 1 })
  await page.addInitScript((t) => localStorage.setItem('otto.theme', t), theme)
  if (before) await page.addInitScript(before)
  await mockApi(page, api)
  await page.goto(APP + path)
  await page.waitForLoadState('networkidle')
  if (setup) await setup(page)
  await page.waitForTimeout(600) // let the calm animations finish
  await page.screenshot({ path: `${OUT}/${name}-${width}-${theme}.png` })
  await page.close()
}

const box = (p) => p.getByRole('textbox', { name: 'Message Otto' })
const out = { signedIn: false }
const emailStep = async (p, email) => {
  await p.getByLabel('Email address').fill(email)
  await p.getByRole('button', { name: 'Continue', exact: true }).click()
}
const newAccount = async (p) => {
  await emailStep(p, 'ada@example.com')
  await p.getByLabel('Your name').fill('Ada Lovelace')
  await p.getByLabel('Password').fill('analytical-engine')
}
const STATES = {
  // "Log in or sign up" (AUTH=1)
  auth: { path: '/login', api: out, setup: (p) => p.getByLabel('Email address').waitFor() },
  authEmailErr: { path: '/login', api: out, setup: async (p) => { await emailStep(p, 'taufik@hey'); await p.getByText('Enter a valid email.').waitFor() } },
  authPw: { path: '/login', api: out, setup: async (p) => { await emailStep(p, 'taufik@hey.com'); await p.getByLabel('Password').fill('ottopass') } },
  authPwErr: {
    path: '/login', api: out,
    setup: async (p) => {
      await emailStep(p, 'taufik@hey.com')
      await p.getByLabel('Password').fill('ottopass')
      await p.getByRole('button', { name: 'Continue', exact: true }).click()
      await p.getByText("That password isn't right.").waitFor()
      await p.getByLabel('Password').blur()
    },
  },
  authNew: { path: '/login', api: out, setup: async (p) => { await newAccount(p); await p.getByLabel('Password').blur() } },
  authForgot: {
    path: '/login', api: out,
    setup: async (p) => {
      await emailStep(p, 'taufik@hey.com')
      await p.getByRole('button', { name: 'Forgot password?' }).click()
      await p.getByText('Check your inbox').waitFor()
    },
  },
  authInvite: {
    path: '/login', api: out,
    setup: async (p) => {
      await newAccount(p)
      await p.getByRole('button', { name: 'Create account' }).click()
      await p.getByText('Otto is invite-only right now.').waitFor()
    },
  },
  authInviteDone: {
    path: '/login', api: out,
    setup: async (p) => {
      await newAccount(p)
      await p.getByRole('button', { name: 'Create account' }).click()
      await p.getByLabel('What would you use Otto for? (optional)').fill('Small fixes on my side projects')
      await p.getByRole('button', { name: 'Request access' }).click()
      await p.getByText('Request sent').waitFor()
    },
  },
  authOffline: {
    path: '/login', api: { ...out, refuse: 'paused' },
    setup: async (p) => {
      await newAccount(p)
      await p.getByRole('button', { name: 'Create account' }).click()
      await p.getByText('Otto is offline right now.').waitFor()
    },
  },
  reset: { path: '/reset-password?token=abc', api: out, setup: (p) => p.getByLabel('New password', { exact: true }).fill('analytical') },
  legalTerms: { path: '/legal/terms', api: out },
  legalPrivacy: { path: '/legal/privacy', api: out },
  legalAup: { path: '/legal/acceptable-use', api: out },
  notfound: { path: '/no/such/page', api: out, setup: (p) => p.waitForTimeout(3200) }, // the mark's one turn
  access: {
    path: '/request-access', api: out,
    setup: (p) => p.getByLabel('GitHub username or email').fill('Taufik041'),
  },
  accessDone: {
    path: '/request-access', api: out,
    setup: async (p) => {
      await p.getByLabel('GitHub username or email').fill('Taufik041')
      await p.getByRole('button', { name: 'Request access' }).click()
      await p.getByText('Request sent').waitFor()
    },
  },
  onboard: { path: '/welcome', api: { me: user({ github_login: null }), github: false } },
  onboarded: { path: '/welcome' },
  empty: { path: '/' },
  mention: { path: '/', setup: async (p) => { await box(p).click(); await p.keyboard.type('@'); await p.getByRole('listbox').waitFor() } },
  mentionOff: {
    path: '/', api: { me: user({ github_login: null }), github: false },
    setup: async (p) => { await box(p).click(); await p.keyboard.type('@'); await p.getByText('Connect GitHub to mention repos').waitFor() },
  },
  models: {
    path: '/',
    setup: async (p) => {
      await box(p).click(); await p.keyboard.type('@otto'); await p.keyboard.press('Enter')
      await p.keyboard.type('fix the failing tests')
      await p.getByRole('button', { name: /^Otto/ }).click()
      await p.getByRole('listbox', { name: 'Models' }).waitFor()
    },
  },
  setAccount: { path: '/settings/account' },
  setGithub: { path: '/settings/github' },
  setUsage: { path: '/settings/usage' },
  setAppearance: { path: '/settings/appearance', before: () => {} },
  // the chat (the mockup's states 6-11)
  working: { path: '/c/s1', api: { chat: 'working' }, setup: (p) => p.getByText('Editing').waitFor() },
  done: { path: '/c/s1', api: { chat: 'done' }, setup: (p) => p.getByText('Pull request opened').waitFor() },
  proposal: { path: '/c/s1', api: { chat: 'proposal' }, setup: (p) => p.getByText('Ready for review').waitFor() },
  declined: { path: '/c/s1', api: { chat: 'declined' }, setup: (p) => p.getByText('Pull request not created').waitFor() },
  workspace: {
    path: '/c/s1',
    api: { chat: 'done' },
    setup: async (p) => {
      await p.getByRole('link', { name: 'See changes ›' }).click()
      await p.getByRole('region', { name: 'Workspace' }).waitFor()
      await p.waitForTimeout(1500) // Shiki
      if ((p.viewportSize()?.width ?? 0) > 500) {
        // the two headers' hairlines must line up
        const a = await p.getByRole('banner').boundingBox()
        const b = await p.getByTestId('workspace-header').boundingBox()
        const ok = a && b && a.y + a.height === b.y + b.height && a.height === 56 && b.height === 56
        console.log(`headers: chat ${a?.y}+${a?.height}, panel ${b?.y}+${b?.height} ${ok ? 'aligned' : 'NOT ALIGNED'}`)
        if (!ok) process.exitCode = 1
      }
    },
  },
  terminal: {
    path: '/c/s1',
    api: { chat: 'done' },
    setup: async (p) => {
      await p.getByRole('button', { name: /\d+ steps/ }).click()
      await p.getByRole('button', { name: /^Ran python -m pytest -q 2 failed/ }).click()
      await p.getByRole('region', { name: 'Workspace' }).waitFor()
    },
  },
  followup: { path: '/c/s1', api: { chat: 'followup' }, setup: (p) => p.getByText('Pull request updated').waitFor() },
  error: { path: '/c/s1', api: { chat: 'error' }, setup: (p) => p.getByText('Something went wrong.').waitFor() },
  limit: { path: '/c/s1', api: { chat: 'limit' }, setup: (p) => p.getByText("You've used today's limit.").waitFor() },
  plain: { path: '/c/s1', api: { chat: 'plain' }, setup: (p) => p.getByText('Mention a repo', { exact: true }).waitFor() },
  // the launch's chat states (LAUNCH=1)
  creating: {
    path: '/c/s1', api: { chat: 'creating' },
    setup: async (p) => {
      await p.getByRole('button', { name: 'Create pull request' }).click()
      await p.getByRole('button', { name: 'Creating pull request…' }).waitFor()
    },
  },
  prError: {
    path: '/c/s1', api: { chat: 'prError' },
    setup: async (p) => {
      await p.getByRole('button', { name: 'Create pull request' }).click()
      await p.getByText("Otto couldn't open the pull request.", { exact: false }).waitFor()
    },
  },
  errSetup: { path: '/c/s1', api: { chat: 'errSetup' }, setup: (p) => p.getByText("Otto couldn't set up the workspace.").waitFor() },
  errPush: { path: '/c/s1', api: { chat: 'errPush' }, setup: (p) => p.getByText("Otto couldn't push to GitHub.").waitFor() },
  errCredit: { path: '/c/s1', api: { chat: 'errCredit' }, setup: (p) => p.getByText("This model's provider is out of credit.").waitFor() },
  modelSwitch: { path: '/c/s1', api: { chat: 'modelSwitch' }, setup: (p) => p.getByText('Switched to GPT-4.1 mini').waitFor() },
  offline: {
    path: '/',
    api: { workers: 'offline' },
    setup: async (p) => {
      await p.getByText("Otto's workers are offline right now. Plain chat still works.").waitFor()
      await box(p).click(); await p.keyboard.type('@otto'); await p.keyboard.press('Enter')
      await p.keyboard.type('fix the failing tests')
    },
  },
  // "Ask Taufik to bring it up", asked
  offlineAsked: {
    path: '/',
    api: { workers: 'offline' },
    setup: async (p) => {
      await p.getByRole('button', { name: 'Ask Taufik to bring it up' }).click()
      await p.getByText('Taufik has been notified.').waitFor()
    },
  },
  offlineChat: {
    path: '/c/s1',
    api: { chat: 'done', workers: 'offline' },
    setup: (p) => p.getByText("Otto's workers are offline right now. Plain chat still works.").waitFor(),
  },
}

// the launch set: every chat state, at 1440 and 390, light and dark
const LAUNCH = ['working', 'proposal', 'creating', 'prError', 'declined', 'done', 'followup', 'workspace', 'modelSwitch',
  'error', 'errSetup', 'errPush', 'errCredit', 'limit', 'offline', 'offlineAsked', 'offlineChat', 'plain', 'empty']

// sign-in, legal, 404 and request access (AUTH=1)
const AUTH = ['auth', 'authEmailErr', 'authPw', 'authPwErr', 'authNew', 'authForgot', 'authInvite', 'authInviteDone', 'authOffline',
  'reset', 'legalTerms', 'legalPrivacy', 'legalAup', 'notfound', 'access', 'accessDone']
const only = process.env.ONLY ? new Set(process.env.ONLY.split(','))
  : process.env.LAUNCH ? new Set(LAUNCH) : process.env.AUTH ? new Set(AUTH) : null // ONLY=done,workspace
for (const width of [1440, 390])
  for (const theme of ['light', 'dark']) {
    for (const [name, s] of Object.entries(STATES)) if (!only || only.has(name)) await shot(name, { width, theme, ...s })
    if (width === 390 && (!only || only.has('drawer')) && !process.env.LAUNCH && !process.env.AUTH) await shot('drawer', { width, theme, path: '/', setup: (p) => p.getByRole('button', { name: 'Open chats' }).click() })
  }

await browser.close()
console.log(`screenshots in ${OUT}/`)
