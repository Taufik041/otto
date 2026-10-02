// End to end against the REAL local backend (gateway, worker, sandboxes, GitHub, the model):
// sign in, start a chat on a repo, watch it to the PR card, send a follow-up, open Changes and
// Terminal, and screenshot the chat at 1440px and 390px in light and dark.
//
//   OTTO_EMAIL=you@example.com OTTO_PASSWORD=... node scripts/e2e.mjs [out-dir]
//   OTTO_REFRESH=<a refresh token> node scripts/e2e.mjs [out-dir]     (e.g. a GitHub-only account)
//
// It opens a real pull request on OTTO_REPO (default Taufik041/otto_test) and spends tokens.
// Needs `npm run dev`, the gateway and a worker (docs/dev.md).
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

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch()

async function context(viewport, theme) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 })
  await ctx.addInitScript((t) => localStorage.setItem('otto.theme', t), theme)
  if (process.env.OTTO_REFRESH) {
    await ctx.addCookies([{ name: 'otto_refresh', value: process.env.OTTO_REFRESH, domain: 'localhost', path: '/auth', httpOnly: true, sameSite: 'Lax' }])
  }
  return ctx
}

async function signIn(page) {
  await page.goto(APP + '/')
  if (process.env.OTTO_REFRESH) return page.getByText('What should we build today').waitFor()
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

// the chat: @repo from the picker, then the task
const box = page.getByRole('textbox', { name: 'Message Otto' })
await box.click()
await page.keyboard.type(`@${SHORT}`)
await page.getByRole('listbox').getByRole('option', { name: new RegExp(SHORT) }).first().waitFor()
await page.keyboard.press('Enter')
await page.keyboard.type(TASK)
await page.keyboard.press('Enter')
await page.waitForURL('**/c/*')
const chatUrl = page.url()
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

// the follow-up
await box.click()
await page.keyboard.type(FOLLOW)
await page.keyboard.press('Enter')
await page.getByText(FOLLOW).waitFor()
await page.screenshot({ path: `${OUT}/followup-sent-1440-light.png` })
await turnEnds(page)
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
    await p.screenshot({ path: `${OUT}/chat-full-${width}-${theme}.png`, fullPage: true })
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
    await ctx.close()
  }
}
log('screenshots in', OUT)
console.log(chatUrl)
await browser.close()
