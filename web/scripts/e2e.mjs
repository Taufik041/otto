// End to end against the REAL local backend (gateway, worker, sandboxes, GitHub, the model):
// sign in, start a chat on a repo, watch it to the PR card, send a follow-up, open Changes and
// Terminal, and screenshot the chat at 1440px and 390px in light and dark.
//
//   OTTO_EMAIL=you@example.com OTTO_PASSWORD=... node scripts/e2e.mjs [out-dir]
//   OTTO_CHAT=http://localhost:5173/c/<id> ...   continue an existing chat (skips starting one)
//
// It opens a real pull request on OTTO_REPO (default Taufik041/otto_test) and spends tokens.
// Needs `npm run dev`, the gateway and a worker (docs/dev.md). It signs in only with the account's
// email and password: never with a minted or copied token.
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const APP = process.env.APP_URL || 'http://localhost:5173'
const REPO = process.env.OTTO_REPO || 'Taufik041/otto_test'
const SHORT = REPO.split('/')[1]
const TASK = process.env.OTTO_TASK || 'two tests are failing, find out why and fix the source, not the tests'
const FOLLOW = process.env.OTTO_FOLLOW_UP || 'also add a test for exactly 11 units'
const OUT = process.argv[2] || 'screenshots/e2e'
const TURN_TIMEOUT = 15 * 60_000
mkdirSync(OUT, { recursive: true })

if (!process.env.OTTO_EMAIL || !process.env.OTTO_PASSWORD) {
  console.error('set OTTO_EMAIL and OTTO_PASSWORD to the account to sign in as')
  process.exit(2)
}

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch()

// the refresh cookie rotates on every refresh, and replaying an old one signs that sign-in out
// everywhere (reuse detection): each context starts from the previous one's cookies
let state = null
async function context(viewport, theme) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1, ...(state ? { storageState: state } : {}) })
  await ctx.addInitScript((t) => localStorage.setItem('otto.theme', t), theme)
  return ctx
}

async function signIn(page) {
  await page.goto(APP + '/')
  if (state) return page.getByText('What should we build today').waitFor() // still signed in
  await page.waitForURL('**/login')
  await page.getByLabel('Email').fill(process.env.OTTO_EMAIL)
  await page.getByLabel('Password').fill(process.env.OTTO_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByText('What should we build today').waitFor()
}

/** Until the turn ends: the composer's Stop turns back into Send. */
async function turnEnds(page) {
  await page.getByRole('button', { name: 'Stop' }).waitFor({ timeout: 60_000 }).catch(() => {})
  await page.getByRole('button', { name: 'Send' }).waitFor({ timeout: TURN_TIMEOUT })
}

const desktop = await context({ width: 1440, height: 900 }, 'light')
const page = await desktop.newPage()
page.on('pageerror', (e) => log('page error:', e.message))
await signIn(page)
log('signed in')

const box = page.getByRole('textbox', { name: 'Message Otto' })
let chatUrl = process.env.OTTO_CHAT
if (chatUrl) {
  await page.goto(chatUrl)
  await page.getByRole('button', { name: 'Send' }).or(page.getByRole('button', { name: 'Stop' })).waitFor()
} else {
  // the chat: @repo from the picker, then the task
  await box.click()
  await page.keyboard.type(`@${SHORT}`)
  await page.getByRole('listbox').getByRole('option', { name: new RegExp(SHORT) }).first().waitFor()
  await page.keyboard.press('Enter')
  await page.keyboard.type(TASK)
  await page.keyboard.press('Enter')
  await page.waitForURL('**/c/*')
  chatUrl = page.url()
  log('started', chatUrl)

  await page.getByText('Setting up workspace…').waitFor({ timeout: 60_000 }).catch(() => log('(setup row not seen)'))
  await page.screenshot({ path: `${OUT}/working-setup-1440-light.png` })
  await page.getByText(/^Running|^Searching|^Reading|^Editing/).first().waitFor({ timeout: 5 * 60_000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}/working-1440-light.png` })
  log('working')

  await turnEnds(page)
  const pr = await page.getByRole('link', { name: /View on GitHub/ }).count()
  log(pr ? 'PR card shown' : 'turn ended without a PR card')
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/done-1440-light.png` })
}

// the follow-up
await box.click()
await page.keyboard.type(FOLLOW)
await page.keyboard.press('Enter')
await page.getByRole('button', { name: 'Stop' }).or(page.getByRole('alert')).first().waitFor({ timeout: 60_000 })
if (await page.getByRole('alert').count()) log('the follow-up was refused:', await page.getByRole('alert').first().innerText())
await page.screenshot({ path: `${OUT}/followup-sent-1440-light.png` })
await turnEnds(page)
log((await page.getByText('Pull request updated').count()) ? 'PR card updated' : (await page.getByText('Pull request opened').count()) ? 'PR card shown' : 'no PR card yet')
await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}/followup-done-1440-light.png` })
log('follow-up done')

// the workspace: Changes, then Terminal
const see = page.getByRole('link', { name: 'See changes ›' }).last()
if (await see.count()) await see.click()
else await page.getByRole('button', { name: 'Workspace' }).click()
const panel = page.getByRole('region', { name: 'Workspace' })
await panel.waitFor()
await page.waitForTimeout(1500) // Shiki
await page.screenshot({ path: `${OUT}/changes-1440-light.png` })
await panel.getByRole('tab', { name: 'Terminal' }).click()
await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}/terminal-1440-light.png` })
state = await desktop.storageState()
await desktop.close()
log('workspace captured')

// the finished chat at every size and theme
for (const width of [1440, 390]) {
  for (const theme of ['light', 'dark']) {
    const ctx = await context({ width, height: width > 500 ? 900 : 844 }, theme)
    const p = await ctx.newPage()
    await signIn(p)
    await p.goto(chatUrl)
    await p.getByRole('button', { name: 'Send' }).waitFor()
    await p.waitForTimeout(1200)
    await p.screenshot({ path: `${OUT}/chat-${width}-${theme}.png` })
    const see2 = p.getByRole('link', { name: 'See changes ›' }).last()
    if (await see2.count()) {
      await see2.click()
      await p.getByRole('region', { name: 'Workspace' }).waitFor()
      await p.waitForTimeout(1500)
      await p.screenshot({ path: `${OUT}/changes-${width}-${theme}.png` })
      await p.getByRole('region', { name: 'Workspace' }).getByRole('tab', { name: 'Terminal' }).click()
      await p.waitForTimeout(500)
      await p.screenshot({ path: `${OUT}/terminal-${width}-${theme}.png` })
    }
    state = await ctx.storageState()
    await ctx.close()
  }
}
// sign out: revokes this sign-in's refresh tokens
const last = await context({ width: 800, height: 600 }, 'light')
const lp = await last.newPage()
await signIn(lp)
await lp.getByRole('button', { name: 'Account menu' }).click()
await lp.getByRole('menuitem', { name: 'Sign out' }).click()
await lp.waitForURL('**/login')
await last.close()
log('signed out; screenshots in', OUT)
console.log(chatUrl)
await browser.close()
