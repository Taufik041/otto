/** Light / Dark / System, System by default (the OS setting, followed live). A choice the user
 *  makes is kept in localStorage; the resolved theme is set as data-theme on <html>, which the CSS
 *  tokens key on, and picks the favicon. index.html applies both before first paint, by the same
 *  rule (keep them in step). */
export type ThemeChoice = 'light' | 'dark' | 'system'
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'otto.theme.v2'
// the key from when Light was the default: its "light" may never have been picked, so only
// "dark" and "system" (which were) still count
export const LEGACY_THEME_KEY = 'otto.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

/** The user's choice, else System. */
export function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
    const old = localStorage.getItem(LEGACY_THEME_KEY)
    return old === 'dark' ? 'dark' : 'system'
  } catch {
    return 'system'
  }
}

/** Only for a choice the user made (Settings → Appearance, the profile menu): never a default. */
export function saveChoice(choice: ThemeChoice) {
  try {
    localStorage.setItem(THEME_KEY, choice)
    localStorage.removeItem(LEGACY_THEME_KEY)
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

export function systemDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK_QUERY).matches
}

export function resolve(choice: ThemeChoice, prefersDark: boolean): Theme {
  return choice === 'system' ? (prefersDark ? 'dark' : 'light') : choice
}

// the page background, for the browser's bar
const BAR: Record<Theme, string> = { light: '#FBFCFD', dark: '#111318' }

/** Set the theme, and the favicon and browser bar that go with it (index.html does the same first). */
export function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
  const set = (sel: string, attr: string, value: string) => document.head.querySelector(sel)?.setAttribute(attr, value)
  set('link[rel="icon"][type="image/svg+xml"]', 'href', `/favicon-${theme}.svg`)
  set('link[rel="icon"][type="image/png"]', 'href', `/favicon-${theme}-32.png`)
  set('link[rel="apple-touch-icon"]', 'href', `/favicon-${theme}-180.png`)
  set('meta[name="theme-color"]', 'content', BAR[theme])
}

export function watchSystem(onChange: (dark: boolean) => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {}
  const mql = window.matchMedia(DARK_QUERY)
  const listener = () => onChange(mql.matches)
  mql.addEventListener('change', listener)
  return () => mql.removeEventListener('change', listener)
}
