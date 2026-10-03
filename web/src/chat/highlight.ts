import { useEffect, useState } from 'react'
import type { HighlighterCore, LanguageRegistration } from 'shiki/core'
import { useTheme } from '@/theme/ThemeProvider'

/** Syntax colors from Shiki with VS Code's own themes (Light+ / Dark+). Shiki, its themes and each
 *  grammar load on first use, with the JavaScript regex engine (no WebAssembly). */
export type Token = { content: string; color?: string }

const THEMES = { light: 'light-plus', dark: 'dark-plus' } as const

type Grammar = () => Promise<{ default: LanguageRegistration[] }>
// the languages diff.ts's languageOf (and fenced code) can name; nothing else is bundled
const GRAMMARS: Record<string, Grammar> = {
  python: () => import('@shikijs/langs/python'),
  typescript: () => import('@shikijs/langs/typescript'),
  tsx: () => import('@shikijs/langs/tsx'),
  javascript: () => import('@shikijs/langs/javascript'),
  jsx: () => import('@shikijs/langs/jsx'),
  json: () => import('@shikijs/langs/json'),
  markdown: () => import('@shikijs/langs/markdown'),
  css: () => import('@shikijs/langs/css'),
  scss: () => import('@shikijs/langs/scss'),
  html: () => import('@shikijs/langs/html'),
  yaml: () => import('@shikijs/langs/yaml'),
  toml: () => import('@shikijs/langs/toml'),
  shellscript: () => import('@shikijs/langs/shellscript'),
  go: () => import('@shikijs/langs/go'),
  rust: () => import('@shikijs/langs/rust'),
  ruby: () => import('@shikijs/langs/ruby'),
  java: () => import('@shikijs/langs/java'),
  kotlin: () => import('@shikijs/langs/kotlin'),
  swift: () => import('@shikijs/langs/swift'),
  c: () => import('@shikijs/langs/c'),
  cpp: () => import('@shikijs/langs/cpp'),
  csharp: () => import('@shikijs/langs/csharp'),
  php: () => import('@shikijs/langs/php'),
  sql: () => import('@shikijs/langs/sql'),
  vue: () => import('@shikijs/langs/vue'),
  svelte: () => import('@shikijs/langs/svelte'),
  ini: () => import('@shikijs/langs/ini'),
  xml: () => import('@shikijs/langs/xml'),
  docker: () => import('@shikijs/langs/docker'),
  make: () => import('@shikijs/langs/make'),
}
// names models write after ``` that mean one of the above
const ALIASES: Record<string, string> = {
  py: 'python', ts: 'typescript', js: 'javascript', md: 'markdown', yml: 'yaml', sh: 'shellscript', bash: 'shellscript',
  shell: 'shellscript', zsh: 'shellscript', console: 'shellscript', rs: 'rust', rb: 'ruby', kt: 'kotlin',
  'c++': 'cpp', cs: 'csharp', dockerfile: 'docker', makefile: 'make',
}

let highlighter: Promise<HighlighterCore> | null = null

function load(): Promise<HighlighterCore> {
  highlighter ??= Promise.all([import('shiki/core'), import('shiki/engine/javascript')]).then(([core, js]) =>
    core.createHighlighterCore({
      themes: [import('@shikijs/themes/light-plus'), import('@shikijs/themes/dark-plus')],
      langs: [],
      engine: js.createJavaScriptRegexEngine(),
    }),
  )
  return highlighter
}

export function grammarFor(lang: string | null): string | null {
  if (!lang) return null
  const l = lang.toLowerCase()
  const id = ALIASES[l] ?? l
  return id in GRAMMARS ? id : null
}

export async function tokenize(code: string, lang: string, theme: 'light' | 'dark'): Promise<Token[][] | null> {
  const id = grammarFor(lang)
  if (!id) return null
  try {
    const h = await load()
    if (!h.getLoadedLanguages().includes(id)) await h.loadLanguage((await GRAMMARS[id]!()).default)
    return h.codeToTokensBase(code, { lang: id, theme: THEMES[theme] })
  } catch {
    return null // offline, or a grammar the regex engine can't run: plain text
  }
}

/** Each line tokenized on its own. Diff hunks and read slices start mid-file (perhaps inside a
 *  string or a docstring), so carrying state across their lines would color them wrong. */
export async function tokenizeLines(lines: string[], lang: string, theme: 'light' | 'dark'): Promise<Token[][] | null> {
  const id = grammarFor(lang)
  if (!id) return null
  try {
    const h = await load()
    if (!h.getLoadedLanguages().includes(id)) await h.loadLanguage((await GRAMMARS[id]!()).default)
    return lines.map((l) => h.codeToTokensBase(l, { lang: id, theme: THEMES[theme] })[0] ?? [])
  } catch {
    return null
  }
}

/** Tokens for `code` by line, or null until (or unless) they're ready. `perLine`: no state across
 *  lines (for fragments of a file). */
export function useTokens(code: string, lang: string | null, perLine = false): Token[][] | null {
  const { theme } = useTheme()
  const id = grammarFor(lang)
  const [tokens, setTokens] = useState<{ key: string; lines: Token[][] | null } | null>(null)
  const key = `${theme}\u0000${id}\u0000${code}`
  useEffect(() => {
    if (!id) return
    let live = true
    const run = perLine ? tokenizeLines(code.split('\n'), id, theme) : tokenize(code, id, theme)
    void run.then((lines) => live && setTokens({ key, lines }))
    return () => {
      live = false
    }
  }, [code, id, theme, key, perLine])
  return tokens?.key === key ? tokens.lines : null
}
