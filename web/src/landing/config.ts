/** The landing page's settings (Vite env, set at build time). */
import { parseOverride } from './status'

const trim = (url: string) => url.replace(/\/+$/, '')

/** The gateway, for GET /health */
export const API_URL = trim(import.meta.env.VITE_API_URL || 'http://localhost:8000')
/** The app: "Get started" and "Log in" go to its /login; the legal pages live there too */
export const APP_URL = trim(import.meta.env.VITE_APP_URL || 'https://ottoci.taufi.dev')
/** auto (ask /health), up or down */
export const STATUS_OVERRIDE = parseOverride(import.meta.env.VITE_STATUS_OVERRIDE)

export const CODE_URL = 'https://github.com/Taufik041/otto'
export const GITHUB_URL = 'https://github.com/Taufik041'
/** The footer's LinkedIn link; hidden when unset */
export const LINKEDIN_URL: string | null = import.meta.env.VITE_LINKEDIN_URL || null
/** "Book a live demo" (the offline dialog, and the app's workers-offline notice); hidden when unset */
export const DEMO_BOOKING_URL: string | null = import.meta.env.VITE_DEMO_BOOKING_URL || null
export const CONTACT_EMAIL = 'hello@taufi.dev'
