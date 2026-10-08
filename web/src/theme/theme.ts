/** Light / Dark / System, Light by default. The choice is kept in localStorage; the resolved theme
 *  is set as data-theme on <html>, which the CSS tokens key on, and picks the favicon. index.html
 *  applies both before first paint. */
export type ThemeChoice = 'light' | 'dark' | 'system'
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'otto.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'dark' || v === 'system' ? v : 'light'
  } catch {
    return 'light'
  }
}

export function saveChoice(choice: ThemeChoice) {
  try {
    localStorage.setItem(THEME_KEY, choice)
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
