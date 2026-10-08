import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  APP_ROUTES, fallback, IMMUTABLE, inlineScriptHashes, isAppRoute, REVALIDATE, securityHeaders, vercelConfig,
} from './site.mjs'

const WEB = resolve(__dirname, '..')
const API = 'https://ottoci-api.taufi.dev'
const read = (f: string) => readFileSync(resolve(WEB, f), 'utf8')
const SAMPLE: Record<string, string> = { doc: 'terms', section: 'usage', id: '4299fa2c3f' }

describe('the app\'s routes', () => {
  it('every <Route path> in App.tsx is served, with any value for its params', () => {
    const paths = [...read('src/App.tsx').matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]!).filter((p) => p !== '*')
    expect(paths.length).toBeGreaterThan(8)
    for (const p of paths) {
      // a real value for each param: /legal/:doc only serves the three documents (others are 404s)
      const filled = p.replace(/:(\w+)\??/g, (_, name: string) => SAMPLE[name] ?? 'abc123')
      expect(isAppRoute(filled), p).toBe(true)
      if (p.includes('?')) expect(isAppRoute(p.replace(/\/:\w+\?/, '')), p).toBe(true)
    }
    expect(isAppRoute('/')).toBe(true) // the index route
  })

  it.each(['/', '/login', '/c/4299fa2c3f', '/settings', '/settings/usage', '/legal/privacy', '/auth/callback', '/welcome/'])(
    '%s is a route', (p) => expect(isAppRoute(p)).toBe(true))

  it.each(['/nope', '/c', '/c/a/b', '/legal/cookies', '/settings/a/b', '/assets/x.js', '/wp-login.php'])(
    '%s is not', (p) => expect(isAppRoute(p)).toBe(false))

  it('the list is what the server rewrites', () => expect(APP_ROUTES).toContain('/c/[^/]+'))
})

describe('paths no file serves', () => {
  it('the app: a route gets index.html; anything else is a real 404 (the app\'s own 404 page)', () => {
    expect(fallback('app', '/c/abc')).toEqual({ file: 'index.html', status: 200 })
    expect(fallback('app', '/nope')).toEqual({ file: 'index.html', status: 404 })
  })

  it('the landing page: 404.html, 404', () => {
    expect(fallback('landing', '/pricing')).toEqual({ file: '404.html', status: 404 })
  })

  it('a missing build file is a plain 404 on both, never a page', () => {
    for (const site of ['app', 'landing'] as const) expect(fallback(site, '/assets/old-a1b2c3.js')).toEqual({ file: null, status: 404 })
  })
})

describe('headers', () => {
  const csp = (h: Record<string, string>) =>
    Object.fromEntries(h['Content-Security-Policy']!.split('; ').map((d) => [d.split(' ')[0], d.split(' ').slice(1)]))

  it('the CSP lets the page reach itself and the API only, and never be framed', () => {
    const h = securityHeaders({ apiUrl: `${API}/`, scriptHashes: ["'sha256-abc'"] })
    const d = csp(h)
    expect(d['connect-src']).toEqual(["'self'", API, 'wss://ottoci-api.taufi.dev'])
    expect(d['script-src']).toEqual(["'self'", "'sha256-abc'"])
    expect(d['default-src']).toEqual(["'self'"])
    expect(d['frame-ancestors']).toEqual(["'none'"])
    expect(d['object-src']).toEqual(["'none'"])
    expect(h['Content-Security-Policy']).not.toMatch(/unsafe-eval|\*/)
    expect(h['Strict-Transport-Security']).toBe('max-age=63072000; includeSubDomains')
    expect(h['X-Content-Type-Options']).toBe('nosniff')
    expect(h['X-Frame-Options']).toBe('DENY')
  })

  it.each(['index.html', 'landing.html', 'landing-404.html'])('%s: its inline pre-paint script is allowed by its hash', (file) => {
    const html = read(file)
    const script = html.match(/<script>([\s\S]*?)<\/script>/)![1]!
    expect(inlineScriptHashes(html)).toEqual([`'sha256-${createHash('sha256').update(script).digest('base64')}'`])
  })

  it('module scripts (src=) need no hash', () => {
    expect(inlineScriptHashes('<script type="module" src="/x.js"></script>')).toEqual([])
  })
})

describe('Vercel\'s Build Output config', () => {
  it.each(['app', 'landing'] as const)('%s: headers first, then files, then the fallbacks', (site) => {
    const { version, routes } = vercelConfig(site, { apiUrl: API, scriptHashes: [] })
    expect(version).toBe(3)
    const fs = routes.findIndex((r) => r.handle === 'filesystem')
    expect(routes.slice(0, fs).every((r) => r.continue === true && r.headers)).toBe(true)
    expect(routes[0]).toMatchObject({ src: '^/assets/(.*)$', headers: { 'Cache-Control': IMMUTABLE } })
    expect(routes[1]).toMatchObject({ headers: { 'Cache-Control': REVALIDATE } })
    // a 404 is never cached for a year: its own Cache-Control replaces the assets' one
    const fresh = { 'Cache-Control': REVALIDATE }
    expect(routes[fs + 1]).toEqual({ src: '^/assets/.*$', status: 404, headers: fresh })
    expect(routes.at(-1)).toEqual(site === 'app'
      ? { src: '^/.*$', dest: '/index.html', status: 404, headers: fresh }
      : { src: '^/.*$', dest: '/404.html', status: 404, headers: fresh })
  })

  it('the app\'s route rewrite matches what isAppRoute says', () => {
    const { routes } = vercelConfig('app', { apiUrl: API, scriptHashes: [] })
    const rewrite = new RegExp(routes.find((r) => r.dest === '/index.html' && !r.status)!.src as string)
    for (const p of ['/', '/c/abc', '/settings/usage', '/legal/terms']) expect(rewrite.test(p)).toBe(true)
    for (const p of ['/nope', '/c/a/b']) expect(rewrite.test(p)).toBe(false)
  })
})
