// End to end against the REAL local backend: a sent message shows once. Sign in, start a plain
// chat, wait for the reply, send a follow-up, wait for its reply, and count the follow-up in the
// thread; then reload (the events replay) and count again. Exits 1 if it shows other than once.
//
//   OTTO_EMAIL=you@example.com OTTO_PASSWORD=... node scripts/e2e-message-once.mjs
//
// A plain chat needs no sandbox, so this runs with the workers offline too; it spends a few
// tokens. Needs `npm run dev`, the gateway and a worker (docs/dev.md). It signs in only with the
// account's email and password: never with a minted or copied token.
import { chromium } from 'playwright'

const APP = process.env.APP_URL || 'http://localhost:5173'
const FIRST = 'In one short sentence: what is a closure?'
const FOLLOW = `And in Python? One sentence. (check ${Date.now().toString(36)})` // unique, so it's countable
const TURN_TIMEOUT = 3 * 60_000

if (!process.env.OTTO_EMAIL || !process.env.OTTO_PASSWORD) {
  console.error('set OTTO_EMAIL and OTTO_PASSWORD to the account to sign in as')
  process.exit(2)
}

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
page.on('pageerror', (e) => log('page error:', e.message))

async function turnEnds() {
  await page.getByRole('button', { name: 'Stop' }).waitFor({ timeout: 30_000 }).catch(() => {})
  await page.getByRole('button', { name: 'Send' }).waitFor({ timeout: TURN_TIMEOUT })
}

/** How often the follow-up shows (a textarea's value isn't text, and the sidebar shows the first message). */
const shown = () => page.getByText(FOLLOW, { exact: true }).count()

let failed = false
try {
  await page.goto(APP + '/')
  await page.waitForURL('**/login')
  await page.getByLabel('Email address').fill(process.env.OTTO_EMAIL)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByLabel('Password').fill(process.env.OTTO_PASSWORD)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByText('What should we build today').waitFor()
  log('signed in')

  const box = page.getByRole('textbox', { name: 'Message Otto' })
  await box.fill(FIRST)
  await page.keyboard.press('Enter')
  await page.waitForURL('**/c/*')
  await turnEnds()
  log('first reply in', page.url())

  await box.fill(FOLLOW)
  await page.keyboard.press('Enter')
  await turnEnds()
  await page.waitForTimeout(1500) // anything late (a NOTIFY after the response) has landed
  const live = await shown()
  log(`after the reply: shown ${live}×`)

  await page.reload()
  await page.getByRole('button', { name: 'Send' }).waitFor()
  await page.waitForTimeout(1000)
  const replayed = await shown()
  log(`after a reload: shown ${replayed}×`)

  failed = live !== 1 || replayed !== 1
  log(failed ? 'FAIL: the follow-up should show exactly once' : 'ok: the follow-up shows once')
} catch (e) {
  failed = true
  log('FAIL:', e.message)
  await page.screenshot({ path: 'screenshots/e2e-message-once-failure.png' }).catch(() => {})
} finally {
  await browser.close()
}
process.exit(failed ? 1 : 0)
