/// <reference types="vitest/config" />
// The app (ottoci.taufi.dev). The landing page is a second build: vite.landing.config.ts.
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, mergeConfig, type UserConfig } from 'vite'
import { previewPlugin } from './vercel/site.mjs'

/** The API the built pages talk to (VITE_API_URL, from the environment or .env files). */
export const apiUrl = loadEnv('production', import.meta.dirname, 'VITE_').VITE_API_URL || 'http://localhost:8000'

/** What both sites share. */
export const shared: UserConfig = {
  plugins: [react(), tailwindcss()],
  // the legal pages' "Last updated"
  define: { __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)) },
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  // Shiki's grammars are lazy chunks loaded per file type; the C++ one alone is ~800 kB
  build: { chunkSizeWarningLimit: 850 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
}

export default mergeConfig(
  shared,
  defineConfig({
    // `vite preview` serves dist/ as production does: the app's routes, real 404s, the headers
    plugins: [previewPlugin('app', apiUrl)],
    server: { port: 5173, strictPort: true },
    preview: { port: 4173, strictPort: true },
  }),
)
