/** Light / Dark / System. The choice is kept in localStorage; the resolved theme is set as
 *  data-theme on <html>, which the CSS tokens key on. index.html applies it before first paint. */
export type ThemeChoice = 'light' | 'dark' | 'system'
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'otto.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function saveChoice(choice: ThemeChoice) {
  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, choice)
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

export function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

export function watchSystem(onChange: (dark: boolean) => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {}
  const mql = window.matchMedia(DARK_QUERY)
  const listener = () => onChange(mql.matches)
  mql.addEventListener('change', listener)
  return () => mql.removeEventListener('change', listener)
}
