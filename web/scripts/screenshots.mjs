// Screenshots of the main screens at 1440px and 390px, light and dark, to compare with the design
// mockup (docs/design/Otto v3.dc.html). The API is mocked with the design brief's sample data, so
// no gateway is needed; the dev server must be running (npm run dev).
//
//   node scripts/screenshots.mjs [out-dir]        (default: screenshots/)
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const APP = process.env.APP_URL || 'http://localhost:5173'
const API = process.env.VITE_API_URL || 'http://localhost:8000'
const OUT = process.argv[2] || 'screenshots'
mkdirSync(OUT, { recursive: true })

const ago = (h) => new Date(Date.now() - h * 3600_000).toISOString()
const user = (over = {}) => ({
  id: 'u1', email: 'taufik@hey.com', name: 'Taufik Khan', github_login: 'Taufik041', avatar_url: null,
  default_model: null, daily_token_limit: 50000, has_password: true, created_at: '2026-09-01T10:00:00+00:00', ...over,
})
const models = {
  default_model: 'openrouter:openrouter/free',
  models: [
    { id: 'openrouter:openrouter/free', label: 'OpenRouter Free', provider: 'openrouter', description: 'Free, good for small tasks', available: true, hint: null },
    { id: 'openai:gpt-4.1-mini', label: 'GPT-4.1 mini', provider: 'openai', description: 'Fast and capable', available: true, hint: null },
    { id: 'openai:gpt-4.1', label: 'GPT-4.1', provider: 'openai', description: 'Best for larger changes', available: false, hint: 'Unavailable right now. Try again later.' },
  ],
}
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
const FAILING =
  "...F..F..                              [100%]\n================ FAILURES ================\n_____ test_bulk_discount_at_threshold _____\nE   AssertionError: Decimal('100.00') != Decimal('90.00')\nFAILED tests/test_pricing.py::test_bulk_discount_at_threshold\nFAILED tests/test_pricing.py::test_invoice_line_at_ten_units\n2 failed, 7 passed in 0.12s"
const PRICING_MD =
  '# Pricing\n\nOrders are priced per unit from the catalog.\nTotals are rounded half-up to the nearest cent.\n\n## Bulk discount\n\nAn order of ten units or more receives a 10% discount\non the subtotal. Smaller orders pay the list price.\n\n`legacy_pricing.py` keeps the old rules and is frozen\nfor historical reports.\n'
const FIX_DIFF = [
  '--- a/src/inventory/pricing.py',
  '+++ b/src/inventory/pricing.py',
  '@@ -20,7 +20,7 @@ CENT = Decimal("0.01")',
  ' ',
  ' ',
  ' def qualifies_for_bulk(quantity: int) -> bool:',
  '     """Orders at or above the threshold get the bulk rate."""',
  '-    return quantity > config.BULK_THRESHOLD',
  '+    return quantity >= config.BULK_THRESHOLD',
  ' ',
  ' ',
  ' def order_total(order: Order) -> Decimal:',
  '',
].join('\n')
const TEST_DIFF = [
  '--- a/tests/test_pricing.py',
  '+++ b/tests/test_pricing.py',
  '@@ -41,3 +41,6 @@ def test_bulk_discount_at_threshold():',
  '     assert order_total(order) == Decimal("90.00")',
  ' ',
  ' ',
  '+def test_bulk_discount_at_eleven_units():',
  '+    order = Order(sku="WIDGET", unit_price=Decimal("10.00"), quantity=11)',
  '+    assert order_total(order) == Decimal("99.00")',
  '',
].join('\n')
const PLAIN_REPLY = [
  'Yes. A threshold rule usually sits next to your other pricing logic and applies to the subtotal:',
  '',
  '```python',
  'def order_total(order: Order) -> Decimal:',
  '    subtotal = order.unit_price * order.quantity',
  '    if subtotal > Decimal("500"):',
  '        subtotal *= Decimal("0.95")',
  '    return round_money(subtotal)',
  '```',
  '',
  'I can write it, add tests and open a pull request once I know which codebase it goes in.',
].join('\n')
const REPLY =
  "Found it. `qualifies_for_bulk` used `>` instead of `>=`, so exactly 10 units missed the bulk discount. The pricing sheet says ten or more qualify.\n\nI fixed the comparison and all 9 tests pass. I left `legacy_pricing.py` alone because it's frozen for historical reports."

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
  const task = plain ? 'Can you add a discount for orders over $500?' : 'two tests are failing, find out why and fix the source, not the tests'
  add('session.created', { task, repo: plain ? null : 'Taufik041/otto_test', model: 'openrouter:openrouter/free' })
  add('session.status', { status: 'running' })
  add('llm.message', { message: { role: 'user', content: task } })
  if (plain) {
    add('llm.message', { message: { role: 'assistant', content: PLAIN_REPLY } })
    add('session.status', { status: 'done' })
    return out
  }
  if (scene === 'limit') {
    add('usage.limit_reached', { used: 50000, limit: 50000, resets_at: '2026-10-03T00:00:00+00:00' })
    add('session.status', { status: 'limited' })
    return out
  }
  add('llm.message', { message: { role: 'assistant', content: "On it. I'll reproduce the failures first.", tool_calls: [{ id: 'c' }] } })
  act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 1, stdout: FAILING, stderr: '' })
  act('code.search', { pattern: 'qualifies_for_bulk' }, ok({ stdout: 'src/inventory/pricing.py:22:def qualifies_for_bulk(quantity: int) -> bool:\nsrc/inventory/legacy_pricing.py:15:def qualifies_for_bulk(qty):' }))
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
  act('fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, ok({ added: 1, removed: 1, diff: FIX_DIFF }))
  act('shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: '.........                                [100%]\n9 passed in 0.09s' }))
  act('git.commit', { message: 'Fix bulk discount threshold' }, ok({ stdout: '[otto/4299fa2c3f 7c1e8a2] Fix bulk discount threshold\n 1 file changed, 1 insertion(+), 1 deletion(-)' }))
  act('git.push', {}, ok({ stderr: 'To github.com:Taufik041/otto_test.git\n * [new branch]      otto/4299fa2c3f -> otto/4299fa2c3f', branch: 'otto/4299fa2c3f', base: 'main', diffstat: { files: 1, additions: 1, deletions: 1 } }))
  add('llm.message', { message: { role: 'assistant', content: REPLY } })
  // the finish proposes the PR; the user opens it ("Create pull request") or not
  add('pr.proposed', { title: 'Fix bulk discount threshold', body: REPLY, head: 'otto/4299fa2c3f', base: 'main',
    additions: 1, deletions: 1, files: 1, tests: { passed: 9, failed: 0, text: '9 passed' } })
  add('session.status', { status: 'done' })
  if (scene === 'proposal') return out
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
async function mockApi(page, { signedIn = true, me = user(), github = true, chat = 'done' } = {}) {
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
    if (path === '/models') return json(route, models)
    if (path === '/repos') return json(route, github ? repos : [])
    if (path === '/github')
      return json(route, { connected: github, login: me.github_login, avatar_url: null, installations: github ? [{ id: 1, account_login: 'Taufik041' }] : [] })
    if (path === '/sessions') return json(route, sessions)
    if (path === '/sessions/s1/events') return json(route, events(chat))
    if (path === '/sessions/s1/ws-ticket') return json(route, { ticket: 't' })
    if (path === '/sessions/s1') {
      const plain = chat === 'plain'
      return json(route, { ...sessions[0], id: 's1', title: plain ? 'Discount for large orders' : 'Fix failing pricing tests',
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
const STATES = {
  signin: {
    path: '/login', api: { signedIn: false },
    setup: async (p) => {
      await p.getByLabel('Email').fill('taufik@hey.com')
      await p.getByLabel('Password').fill('ottopass')
      await p.getByRole('button', { name: 'Sign in' }).click()
      await p.getByText("That password isn't right.").waitFor()
      await p.getByLabel('Password').blur()
    },
  },
  signup: { path: '/signup', api: { signedIn: false } },
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
      await p.getByRole('button', { name: /OpenRouter Free/ }).click()
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
    },
  },
  terminal: {
    path: '/c/s1',
    api: { chat: 'done' },
    setup: async (p) => {
      await p.getByRole('button', { name: /7 steps/ }).click()
      await p.getByRole('button', { name: /^Ran python -m pytest -q 2 failed/ }).click()
      await p.getByRole('region', { name: 'Workspace' }).waitFor()
    },
  },
  followup: { path: '/c/s1', api: { chat: 'followup' }, setup: (p) => p.getByText('Pull request updated').waitFor() },
  error: { path: '/c/s1', api: { chat: 'error' }, setup: (p) => p.getByText("Otto couldn't finish.").waitFor() },
  limit: { path: '/c/s1', api: { chat: 'limit' }, setup: (p) => p.getByText("You've used today's limit.").waitFor() },
  plain: { path: '/c/s1', api: { chat: 'plain' }, setup: (p) => p.getByText('Mention a repo', { exact: true }).waitFor() },
}

const only = process.env.ONLY ? new Set(process.env.ONLY.split(',')) : null // ONLY=done,workspace
for (const width of [1440, 390])
  for (const theme of ['light', 'dark']) {
    for (const [name, s] of Object.entries(STATES)) if (!only || only.has(name)) await shot(name, { width, theme, ...s })
    if (width === 390 && (!only || only.has('drawer'))) await shot('drawer', { width, theme, path: '/', setup: (p) => p.getByRole('button', { name: 'Open chats' }).click() })
  }

await browser.close()
console.log(`screenshots in ${OUT}/`)
