import { act, render, screen } from '@testing-library/react'
import { createElement } from 'react'
import INDEX from '../../index.html?raw'
import { apply, LEGACY_THEME_KEY, readChoice, resolve, saveChoice, THEME_KEY } from './theme'
import { ThemeProvider, useTheme } from './ThemeProvider'

/** The OS setting, and the listeners the page put on it, so a test can switch it live. */
let osDark = false
const listeners = new Set<() => void>()
function prefersDark(dark: boolean) {
  osDark = dark
  window.matchMedia = ((q: string) => ({
    get matches() {
      return osDark && q.includes('dark')
    },
    addEventListener: (_: string, l: () => void) => listeners.add(l),
    removeEventListener: (_: string, l: () => void) => listeners.delete(l),
  })) as never
}
function osSwitches(dark: boolean) {
  osDark = dark
  act(() => listeners.forEach((l) => l()))
}

/** index.html's head: its icon links and the script that sets the theme before first paint */
function loadHead() {
  document.head.innerHTML = INDEX.match(/<head>([\s\S]*)<\/head>/)![1]!.replace(/<script>[\s\S]*?<\/script>/, '')
  const script = INDEX.match(/<script>([\s\S]*?)<\/script>/)![1]!
  new Function(script)()
}

const href = (sel: string) => document.head.querySelector(sel)?.getAttribute('href')
const icons = () => ({
  svg: href('link[rel="icon"][type="image/svg+xml"]'),
  png: href('link[rel="icon"][type="image/png"]'),
  touch: href('link[rel="apple-touch-icon"]'),
})
const LIGHT_ICONS = { svg: '/favicon-light.svg', png: '/favicon-light-32.png', touch: '/favicon-light-180.png' }
const DARK_ICONS = { svg: '/favicon-dark.svg', png: '/favicon-dark-32.png', touch: '/favicon-dark-180.png' }

/** The app's provider, showing the choice and the theme it resolves to, with a button per choice. */
function Probe() {
  const t = useTheme()
  return createElement(
    'div',
    null,
    createElement('p', { 'data-testid': 'theme' }, `${t.choice}:${t.theme}`),
    ...(['light', 'dark', 'system'] as const).map((c) => createElement('button', { key: c, onClick: () => t.setChoice(c) }, c)),
  )
}
const app = () => render(createElement(ThemeProvider, null, createElement(Probe)))
const shown = () => screen.getByTestId('theme').textContent
const choose = (c: 'light' | 'dark' | 'system') => act(() => screen.getByRole('button', { name: c }).click())

beforeEach(() => {
  localStorage.clear()
  listeners.clear()
  prefersDark(false)
  delete document.documentElement.dataset.theme
})

describe('the default theme is System', () => {
  it('with nothing chosen: System, which follows the OS', () => {
    expect(readChoice()).toBe('system')
    expect(resolve(readChoice(), false)).toBe('light')
    expect(resolve(readChoice(), true)).toBe('dark')
  })

  it('a dark OS gives dark, and the app follows when the OS switches, live', () => {
    prefersDark(true)
    app()
    expect(shown()).toBe('system:dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    osSwitches(false)
    expect(shown()).toBe('system:light')
    expect(document.documentElement.dataset.theme).toBe('light')
    osSwitches(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('an explicit choice wins over the OS, is remembered, and stops following it', () => {
    prefersDark(true)
    app()
    choose('light')
    expect(shown()).toBe('light:light')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
    osSwitches(false)
    osSwitches(true)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(readChoice()).toBe('light') // the next visit too
  })

  it('choosing System again follows the OS again, and is remembered as a choice', () => {
    saveChoice('dark')
    app()
    choose('system')
    expect(localStorage.getItem(THEME_KEY)).toBe('system')
    expect(shown()).toBe('system:light')
    osSwitches(true)
    expect(shown()).toBe('system:dark')
  })

  it('junk in storage is no choice', () => {
    localStorage.setItem(THEME_KEY, 'purple')
    expect(readChoice()).toBe('system')
  })
})

describe('a choice stored before System was the default', () => {
  it('a stored "light" from back then pins nobody: it may never have been picked', () => {
    prefersDark(true)
    localStorage.setItem(LEGACY_THEME_KEY, 'light')
    expect(readChoice()).toBe('system')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it.each(['dark', 'system'] as const)('"%s" was picked (it wasn\'t the default), so it carries over', (old) => {
    prefersDark(true)
    localStorage.setItem(LEGACY_THEME_KEY, old)
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(readChoice()).toBe(old)
  })

  it('a choice made since wins over the old one', () => {
    localStorage.setItem(LEGACY_THEME_KEY, 'dark')
    saveChoice('light')
    expect(readChoice()).toBe('light')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})

describe('before first paint, index.html follows the same rule', () => {
  it('nothing chosen: the OS setting', () => {
    prefersDark(true)
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')
    prefersDark(false)
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('a choice wins over the OS', () => {
    prefersDark(true)
    localStorage.setItem(THEME_KEY, 'light')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('light')
    prefersDark(false)
    localStorage.setItem(THEME_KEY, 'dark')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')
    localStorage.setItem(THEME_KEY, 'system')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('no flash: what it paints is what the app then applies', () => {
    for (const [os, stored] of [[true, null], [false, null], [true, 'light'], [false, 'dark'], [true, 'system']] as const) {
      localStorage.clear()
      if (stored) localStorage.setItem(THEME_KEY, stored)
      prefersDark(os)
      loadHead()
      const painted = document.documentElement.dataset.theme
      expect(resolve(readChoice(), os)).toBe(painted)
    }
  })
})

describe('the favicon follows the active theme', () => {
  it('index.html starts with the active theme\'s icons: System resolves to light or dark', () => {
    loadHead()
    expect(icons()).toEqual(LIGHT_ICONS)
    prefersDark(true)
    loadHead()
    expect(icons()).toEqual(DARK_ICONS)
    localStorage.setItem(THEME_KEY, 'light')
    loadHead()
    expect(icons()).toEqual(LIGHT_ICONS)
  })

  it('switching the theme in the app swaps every icon', () => {
    loadHead()
    apply('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(icons()).toEqual(DARK_ICONS)
    apply('light')
    expect(icons()).toEqual(LIGHT_ICONS)
  })

  it('the icons follow the OS live while on System', () => {
    loadHead()
    app()
    expect(icons()).toEqual(LIGHT_ICONS)
    osSwitches(true)
    expect(icons()).toEqual(DARK_ICONS)
  })

  it('the browser bar color follows too', () => {
    loadHead()
    apply('dark')
    expect(document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#111318')
    apply('light')
    expect(document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#FBFCFD')
  })
})
