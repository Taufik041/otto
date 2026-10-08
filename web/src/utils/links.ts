/** Where Otto lives outside this app. */

/** The landing page (its #demo is the live replay): VITE_LANDING_URL, else otto.taufi.dev */
export const LANDING_URL: string = (import.meta.env.VITE_LANDING_URL || 'https://otto.taufi.dev').replace(/\/+$/, '')

export const CONTACT_EMAIL = 'hello@taufi.dev'

/** "Book a live demo" beside the workers-offline notice; hidden when unset */
export const DEMO_BOOKING_URL: string | null = import.meta.env.VITE_DEMO_BOOKING_URL || null

/** "Continue with Google" shows only with VITE_GOOGLE_AUTH=1 (off: there is no Google sign-in yet). */
export const GOOGLE_AUTH = import.meta.env.VITE_GOOGLE_AUTH === '1'

/** The day this build was made, for the legal pages' "Last updated" (vite.config.ts sets it). */
export const BUILD_DATE: string = typeof __BUILD_DATE__ === 'string' ? __BUILD_DATE__ : new Date().toISOString().slice(0, 10)
