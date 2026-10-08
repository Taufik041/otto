import INDEX from '../../index.html?raw'
import { apply, readChoice, resolve, saveChoice, THEME_KEY } from './theme'

function prefersDark(dark: boolean) {
  window.matchMedia = ((q: string) => ({ matches: dark && q.includes('dark'), addEventListener() {}, removeEventListener() {} })) as never
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

beforeEach(() => {
  localStorage.clear()
  prefersDark(false)
  delete document.documentElement.dataset.theme
})

describe('the default theme', () => {
  it('is Light when nothing was chosen, even if the system is dark', () => {
    prefersDark(true)
    expect(readChoice()).toBe('light')
    expect(resolve(readChoice(), true)).toBe('light')
  })

  it('System is a choice of its own, kept like the others', () => {
    saveChoice('system')
    expect(localStorage.getItem(THEME_KEY)).toBe('system')
    expect(readChoice()).toBe('system')
    saveChoice('dark')
    expect(readChoice()).toBe('dark')
  })

  it('index.html paints Light before the app loads, unless Dark or System (on a dark system) was chosen', () => {
    prefersDark(true)
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('light')

    localStorage.setItem(THEME_KEY, 'system')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')

    prefersDark(false)
    localStorage.setItem(THEME_KEY, 'dark')
    loadHead()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})

describe('the favicon follows the active theme', () => {
  it('index.html starts with the active theme\'s icons', () => {
    loadHead()
    expect(icons()).toEqual({ svg: '/favicon-light.svg', png: '/favicon-light-32.png', touch: '/favicon-light-180.png' })
    localStorage.setItem(THEME_KEY, 'dark')
    loadHead()
    expect(icons()).toEqual({ svg: '/favicon-dark.svg', png: '/favicon-dark-32.png', touch: '/favicon-dark-180.png' })
  })

  it('switching the theme in the app swaps every icon', () => {
    loadHead()
    apply('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(icons()).toEqual({ svg: '/favicon-dark.svg', png: '/favicon-dark-32.png', touch: '/favicon-dark-180.png' })
    apply('light')
    expect(icons()).toEqual({ svg: '/favicon-light.svg', png: '/favicon-light-32.png', touch: '/favicon-light-180.png' })
  })

  it('the browser bar color follows too', () => {
    loadHead()
    apply('dark')
    expect(document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#111318')
    apply('light')
    expect(document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#FBFCFD')
  })
})
