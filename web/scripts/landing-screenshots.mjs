// Screenshots of the landing page at 1440px and 390px, light and dark, to compare with the design
// mockup (docs/design/Otto v4.dc.html). GET /health is mocked (live, chat only, or unreachable),
// so no gateway is needed; the landing's dev server must be running (npm run dev:landing), and
// answers the offline dialog's form itself (it logs the email).
const health = { live: { status: 'up', workers: 'online' }, chat: { status: 'up', workers: 'offline' } }
//
//   node scripts/landing-screenshots.mjs [out-dir]     (default: screenshots/landing/)
//   ONLY=live,menu node scripts/landing-screenshots.mjs
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const SITE = process.env.LANDING_URL || 'http://localhost:5174'
const OUT = process.argv[2] || 'screenshots/landing'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()

async function shot(name, { width, scheme, path = '/', state = 'live', reduced = false, full = false, setup }) {
  const page = await browser.newPage({
    viewport: { width, height: width > 500 ? 900 : 844 },
    colorScheme: scheme,
    reducedMotion: reduced ? 'reduce' : 'no-preference',
    deviceScaleFactor: 1,
  })
  await page.route('**/health', (route) =>
    state === 'offline' // the gateway can't be reached
      ? route.abort('connectionrefused')
      : route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' },
          body: JSON.stringify({ ...health[state], version: 'screenshots' }) }))
  await page.goto(SITE + path)
  await page.waitForLoadState('networkidle')
  if (setup) await setup(page)
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}/${name}-${width}-${scheme}.png`, fullPage: full })
  await page.close()
}

// the status pill: "Live" / "Chat only" / "Offline" on desktop; on phones a dot, with the words for screen readers
const pill = (p, word) => p.getByRole('status').filter({ hasText: word }).waitFor()
async function openDialog(p) {
  await pill(p, /offline/i)
  await p.getByRole('link', { name: 'Get started' }).first().click()
  await p.getByRole('dialog', { name: 'Otto is offline right now.' }).waitFor()
}
const toDemo = (p) => p.evaluate(() => document.querySelector('#demo').scrollIntoView({ block: 'center' }))
const STATES = {
  // the hero, live, at three moments of the replay
  live: { setup: (p) => pill(p, /live/i) },
  'replay-working': { setup: async (p) => { await toDemo(p); await p.waitForTimeout(12_500) } },
  'replay-click': { setup: async (p) => { await toDemo(p); await p.getByText('Creating pull request…').waitFor({ timeout: 40_000 }) } },
  'replay-opened': { setup: async (p) => { await toDemo(p); await p.locator('[data-replay]').getByText('Pull request opened').waitFor({ timeout: 40_000 }) } },
  // the whole page, live
  full: { full: true, setup: (p) => pill(p, /live/i) },
  // reduced motion: the replay's final state, still
  still: { reduced: true, setup: toDemo },
  // chat only: up, but the sandboxes are offline (amber); Get started still goes to the app
  chat: { state: 'chat', full: true, setup: (p) => pill(p, /chat (only|is live)/i) },
  // offline: the pill, and Get started opens the dialog: its intro, the form, and "Sent."
  offline: { state: 'offline', setup: (p) => pill(p, /offline/i) },
  'offline-dialog': { state: 'offline', setup: openDialog },
  'offline-form': {
    state: 'offline',
    setup: async (p) => {
      await openDialog(p)
      await p.getByRole('button', { name: 'Bring it back up' }).click()
      await p.getByLabel('Your email').fill('ada@example.com')
    },
  },
  'offline-sent': {
    state: 'offline',
    setup: async (p) => {
      await openDialog(p)
      await p.getByRole('button', { name: 'Bring it back up' }).click()
      await p.getByLabel('Your email').fill('ada@example.com')
      // a fresh address per shot, so the dev server's limit (3 an hour per IP) never kicks in
      await p.route('**/api/wake', (r) => r.continue({ headers: { ...r.request().headers(), 'x-forwarded-for': `198.51.100.${Math.floor(Math.random() * 250) + 1}` } }))
      await p.waitForTimeout(3200) // the form's 3 seconds
      await p.getByRole('button', { name: 'Send', exact: true }).click()
      await p.getByRole('dialog', { name: 'Sent.' }).waitFor()
    },
  },
  // phones: the menu sheet, live and offline
  menu: { phone: true, setup: async (p) => { await p.getByRole('button', { name: 'Menu' }).click(); await p.getByRole('dialog', { name: 'Menu' }).waitFor() } },
  'menu-offline': {
    phone: true,
    state: 'offline',
    setup: async (p) => {
      await pill(p, /offline/i)
      await p.getByRole('button', { name: 'Menu' }).click()
    },
  },
  notfound: { path: '/404', setup: (p) => p.waitForTimeout(3200) }, // the mark's one turn
}

const only = process.env.ONLY ? new Set(process.env.ONLY.split(',')) : null
for (const width of [1440, 390])
  for (const scheme of ['light', 'dark'])
    for (const [name, s] of Object.entries(STATES)) {
      if (only && !only.has(name)) continue
      if (s.phone && width > 500) continue // the menu is a phone's
      await shot(name, { width, scheme, ...s })
    }

await browser.close()
console.log(`screenshots in ${OUT}/`)
