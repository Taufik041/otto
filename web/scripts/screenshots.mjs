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
const sessions = [
  ['s1', 'Fix failing pricing tests', 'done', 'Taufik041/otto_test', 1],
  ['s2', 'Portfolio contact form', 'running', 'Taufik041/portfolio', 2],
  ['s3', 'Add line_count() to Order', 'done', 'Taufik041/otto_test', 26],
  ['s4', 'Explain the catalog module', 'done', null, 80],
  ['s5', 'Refactor shipping fees', 'failed', 'Taufik041/otto_test', 300],
].map(([id, title, status, repo, h]) => ({ id, title, status, repo, model: models.default_model, pr_url: null, updated_at: ago(h) }))
const DAILY = [8.2, 14.1, 6.3, 0, 3.4, 18.9, 22.4, 11.2, 9.8, 16.5, 4.1, 0, 7.7, 12.4]
const usage = {
  today: { tokens: 12400, limit: 50000, resets_at: '2026-10-02T00:00:00+00:00' },
  month: { sessions: 38, tokens: 412000, est_cost_usd: 0 },
  daily: DAILY.map((v, i) => ({ date: new Date(Date.now() - (13 - i) * 86400_000).toISOString().slice(0, 10), tokens: Math.round(v * 1000) })),
  by_model: [{ model: 'openrouter:openrouter/free', tokens: 388000, est_cost_usd: 0 }, { model: 'openai:gpt-4.1-mini', tokens: 24000, est_cost_usd: 0 }],
  active_sandboxes: [{ session_id: 's2', title: 'Portfolio contact form', repo: 'Taufik041/portfolio', sandbox_status: 'running' }],
}

/** Answer the gateway's routes; `signedIn: false` refuses the refresh cookie. */
async function mockApi(page, { signedIn = true, me = user(), github = true } = {}) {
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
}

for (const width of [1440, 390])
  for (const theme of ['light', 'dark']) {
    for (const [name, s] of Object.entries(STATES)) await shot(name, { width, theme, ...s })
    if (width === 390) await shot('drawer', { width, theme, path: '/', setup: (p) => p.getByRole('button', { name: 'Open chats' }).click() })
  }

await browser.close()
console.log(`screenshots in ${OUT}/`)
