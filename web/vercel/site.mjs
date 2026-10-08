// How the two sites built from web/ are served: which paths exist, what a missing one gets, and
// the headers. One source for production (scripts/vercel-output.mjs writes Vercel's Build Output
// config from it) and for `vite preview` (previewPlugin), so a local preview behaves the same.
//
//   app      ottoci.taufi.dev   a single-page app: its routes get index.html; anything else is a
//                               real 404 (index.html again, with status 404: the app's own page)
//   landing  otto.taufi.dev     static pages: / and its files; anything else is 404.html, 404
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/** The app's client-side routes (src/App.tsx), as anchored regular expressions. */
export const APP_ROUTES = [
  '/',
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/request-access',
  '/auth/callback',
  '/welcome',
  '/settings',
  '/settings/[^/]+',
  '/c/[^/]+',
  '/legal/(?:terms|privacy|acceptable-use)',
]
const APP_ROUTE = new RegExp(`^(?:${APP_ROUTES.join('|')})/?$`)
export const isAppRoute = (path) => APP_ROUTE.test(path)

/** Built files with a content hash in their name: cached for a year. */
export const ASSETS = '/assets/'
export const IMMUTABLE = 'public, max-age=31536000, immutable'
/** Everything else (HTML, favicons): always revalidated, so a deploy shows at once. */
export const REVALIDATE = 'public, max-age=0, must-revalidate'

/** 'sha256-…' for each inline <script> in the page: the CSP allows exactly those. */
export function inlineScriptHashes(html) {
  const hashes = []
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g))
    hashes.push(`'sha256-${createHash('sha256').update(m[1], 'utf8').digest('base64')}'`)
  return hashes
}

/** The API's origin and its WebSocket twin (https://x → wss://x). */
export function apiOrigins(apiUrl) {
  const origin = new URL(apiUrl).origin
  return [origin, origin.replace(/^http/, 'ws')]
}

/**
 * The security headers. The CSP lets the page talk to itself and the API only; scripts are the
 * site's own files and its hashed inline ones. Styles allow inline (dialogs inject a <style>
 * tag); images allow GitHub avatars (the app) and data: URIs.
 */
export function securityHeaders({ apiUrl, scriptHashes }) {
  const csp = [
    "default-src 'self'",
    `script-src 'self' ${scriptHashes.join(' ')}`.trim(),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://avatars.githubusercontent.com",
    "font-src 'self'",
    `connect-src 'self' ${apiOrigins(apiUrl).join(' ')}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join('; ')
  return {
    'Content-Security-Policy': csp,
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
  }
}

/** The page that answers a path no file serves: { file, status }. */
export function fallback(site, path) {
  if (path.startsWith(ASSETS)) return { file: null, status: 404 } // a missing build file: no page
  if (site === 'app') return { file: 'index.html', status: isAppRoute(path) ? 200 : 404 }
  return { file: '404.html', status: 404 }
}

/** Vercel's Build Output API config (v3) for a site. */
export function vercelConfig(site, { apiUrl, scriptHashes }) {
  const security = securityHeaders({ apiUrl, scriptHashes })
  const routes = [
    { src: `^${ASSETS}(.*)$`, headers: { 'Cache-Control': IMMUTABLE }, continue: true },
    { src: `^(?!${ASSETS}).*$`, headers: { 'Cache-Control': REVALIDATE }, continue: true },
    { src: '^/(.*)$', headers: security, continue: true },
    { handle: 'filesystem' },
    // what follows is what no file answered: never cache a 404 for a year (a later route's
    // header replaces the immutable one set above)
    { src: `^${ASSETS}.*$`, status: 404, headers: { 'Cache-Control': REVALIDATE } },
  ]
  if (site === 'app') {
    routes.push(
      { src: APP_ROUTE.source, dest: '/index.html' },
      { src: '^/.*$', dest: '/index.html', status: 404, headers: { 'Cache-Control': REVALIDATE } },
    )
  } else {
    routes.push({ src: '^/.*$', dest: '/404.html', status: 404, headers: { 'Cache-Control': REVALIDATE } })
  }
  return { version: 3, routes }
}

/**
 * `vite preview` as production serves it: the same headers, and the same answers for paths no
 * file serves (the app's routes, real 404s). outDir: the build's output folder.
 */
export function previewPlugin(site, apiUrl) {
  return {
    name: `otto-${site}-preview`,
    configurePreviewServer(server) {
      const outDir = server.config.build.outDir
      const page = (file) => readFileSync(join(outDir, file), 'utf8')
      const security = securityHeaders({ apiUrl, scriptHashes: inlineScriptHashes(page('index.html')) })
      server.middlewares.use((req, res, next) => {
        const path = decodeURIComponent((req.url ?? '/').split(/[?#]/)[0])
        for (const [k, v] of Object.entries(security)) res.setHeader(k, v)
        res.setHeader('Cache-Control', path.startsWith(ASSETS) ? IMMUTABLE : REVALIDATE)
        const isFile = path !== '/' && existsSync(join(outDir, path)) && !path.endsWith('/')
        if (isFile || path === '/' || path === '/index.html') return next()
        const { file, status } = fallback(site, path)
        if (status === 200) return next() // the app's route: vite's own fallback serves index.html
        res.statusCode = status
        res.setHeader('Cache-Control', REVALIDATE) // a 404 is never cached for long
        res.setHeader('Content-Type', file ? 'text/html; charset=utf-8' : 'text/plain; charset=utf-8')
        res.end(file ? page(file) : 'Not found')
      })
    },
  }
}
