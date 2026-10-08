// Vercel's Build Output API for one of the two sites built from web/: copies the build into
// .vercel/output/static and writes .vercel/output/config.json (routes, real 404s, headers) from
// vercel/site.mjs. Vercel serves .vercel/output as it is, so each project needs only its build
// command (package.json):
//   app      npm run vercel:app       (ottoci.taufi.dev)
//   landing  npm run vercel:landing   (otto.taufi.dev)
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { inlineScriptHashes, vercelConfig } from '../vercel/site.mjs'

const site = process.argv[2]
if (site !== 'app' && site !== 'landing') {
  console.error('usage: node scripts/vercel-output.mjs app|landing')
  process.exit(2)
}
const dist = site === 'app' ? 'dist' : 'dist-landing'
const pages = site === 'app' ? ['index.html'] : ['index.html', '404.html']

// the API the CSP lets pages reach: the same VITE_API_URL the build compiled in
const apiUrl = process.env.VITE_API_URL
if (!apiUrl && process.env.VERCEL_ENV === 'production') {
  console.error('VITE_API_URL is not set: a production build needs the API it talks to (and its CSP)')
  process.exit(1)
}
for (const page of pages) if (!existsSync(`${dist}/${page}`)) {
  console.error(`${dist}/${page} is missing: build first`)
  process.exit(1)
}

const scriptHashes = [...new Set(pages.flatMap((p) => inlineScriptHashes(readFileSync(`${dist}/${p}`, 'utf8'))))]
const out = '.vercel/output'
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })
cpSync(dist, `${out}/static`, { recursive: true })
// the landing's function: POST /api/wake ("Bring it back up"), which works while the API is down
if (site === 'landing') {
  const fn = `${out}/functions/api/wake.func`
  mkdirSync(fn, { recursive: true })
  cpSync('vercel/functions/wake.mjs', `${fn}/index.mjs`)
  cpSync('vercel/wake.mjs', `${fn}/wake.mjs`)
  cpSync('vercel/node.mjs', `${fn}/node.mjs`)
  writeFileSync(`${fn}/.vc-config.json`, JSON.stringify({ runtime: 'nodejs22.x', handler: 'index.mjs', launcherType: 'Nodejs' }, null, 2) + '\n')
}
const config = vercelConfig(site, { apiUrl: apiUrl || 'http://localhost:8000', scriptHashes })
writeFileSync(`${out}/config.json`, JSON.stringify(config, null, 2) + '\n')
console.log(`${out}: ${site} (${dist}), API ${apiUrl || 'http://localhost:8000 (VITE_API_URL unset)'}, ${config.routes.length} routes`)
