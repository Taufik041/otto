/// <reference types="vitest/config" />
// The landing page (otto.taufi.dev): a second build of this project, sharing the app's code.
//   npm run dev:landing     http://localhost:5174
//   npm run build:landing   dist-landing/ (index.html, 404.html, assets/)
import type { IncomingMessage, ServerResponse } from 'node:http'
import { defineConfig, mergeConfig, type Plugin } from 'vite'
import { apiUrl, shared } from './vite.config.ts'
import { clientIp, toRequest, writeResponse } from './vercel/node.mjs'
import { previewPlugin } from './vercel/site.mjs'
import { handleWake, logEmail } from './vercel/wake.mjs'

const PAGES: Record<string, string> = { 'landing.html': 'index.html', 'landing-404.html': '404.html' }

/** landing.html is the site's index.html, and landing-404.html its 404.html, as a static host
 *  expects; in dev, / is the landing page and /404 its 404. */
function pageNames(): Plugin {
  return {
    name: 'otto-landing-pages',
    enforce: 'post',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const path = (req.url ?? '/').split(/[?#]/)[0]
        if (path === '/' || path === '/index.html') req.url = '/landing.html'
        else if (path === '/404' || path === '/404.html') req.url = '/landing-404.html'
        next()
      })
    },
    generateBundle(_, bundle) {
      for (const [from, to] of Object.entries(PAGES)) {
        const page = bundle[from]
        if (page?.type !== 'asset') continue
        delete bundle[from]
        this.emitFile({ type: 'asset', fileName: to, source: page.source })
      }
    },
  }
}

/** POST /api/wake in dev and preview: the Vercel function's handler, logging the email instead of
 *  sending it (OTTO_NOTIFY_TO names the inbox in the log). */
function wakeApi(): Plugin {
  const env = { RESEND_API_KEY: 'dev (logged, not sent)', OTTO_NOTIFY_TO: process.env.OTTO_NOTIFY_TO || 'taufik@localhost.test' }
  const middleware = async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    if ((req.url ?? '').split('?')[0] !== '/api/wake') return next()
    const response = await handleWake(await toRequest(req), { env, send: logEmail, ip: clientIp(req) })
    await writeResponse(res, response)
  }
  return {
    name: 'otto-landing-wake',
    configureServer: (server) => void server.middlewares.use(middleware),
    configurePreviewServer: (server) => void server.middlewares.use(middleware),
  }
}

export default mergeConfig(
  shared,
  defineConfig({
    appType: 'mpa', // no fallback to the app's index.html
    // `vite preview` serves dist-landing/ as production does: its pages, 404.html, the headers
    // wakeApi first: preview's 404s would answer /api/wake otherwise
    plugins: [wakeApi(), pageNames(), previewPlugin('landing', apiUrl)],
    server: { port: 5174, strictPort: true },
    preview: { port: 4174, strictPort: true },
    build: { outDir: 'dist-landing', rollupOptions: { input: { landing: 'landing.html', notfound: 'landing-404.html' } } },
  }),
)
