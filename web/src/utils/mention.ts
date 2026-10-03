import type { Repo } from '@/api/types'

/** The "@query" being typed: from an @ at the start or after whitespace, up to the caret. */
export type ActiveMention = { start: number; end: number; query: string }

const MENTION_AT_CARET = /(^|\s)@([\w.\-/]*)$/

export function activeMention(text: string, caret: number = text.length): ActiveMention | null {
  const m = MENTION_AT_CARET.exec(text.slice(0, caret))
  if (!m) return null
  const start = m.index + m[1]!.length
  return { start, end: caret, query: m[2]! }
}

export function shortName(fullName: string): string {
  return fullName.slice(fullName.indexOf('/') + 1)
}

export function ownerOf(fullName: string): string {
  return fullName.slice(0, fullName.indexOf('/'))
}

/** Repos whose full name contains the query (any case); those whose name starts with it first. */
export function filterRepos(repos: Repo[], query: string): Repo[] {
  const q = query.trim().toLowerCase()
  if (!q) return repos
  const hits = repos.filter((r) => r.full_name.toLowerCase().includes(q))
  const starts = (r: Repo) => shortName(r.full_name).toLowerCase().startsWith(q) || r.full_name.toLowerCase().startsWith(q)
  return [...hits.filter(starts), ...hits.filter((r) => !starts(r))]
}

/** The text without the "@query" (the repo goes into a chip instead), and where the caret goes. */
export function removeMention(text: string, m: ActiveMention): { text: string; caret: number } {
  const after = text.slice(m.end)
  const before = text.slice(0, m.start)
  const joined = before.endsWith(' ') && after.startsWith(' ') ? before + after.slice(1) : before + after
  return { text: joined, caret: m.start }
}

/** The repo a typed "@name" or "@owner/name" refers to: an exact full name, or a short name only
 *  one repo has. */
export function findRepo(repos: Repo[], name: string): Repo | null {
  const n = name.toLowerCase()
  const exact = repos.find((r) => r.full_name.toLowerCase() === n)
  if (exact) return exact
  const short = repos.filter((r) => shortName(r.full_name).toLowerCase() === n)
  return short.length === 1 ? short[0]! : null
}

const MENTION = /(^|\s)@([\w.\-]+(?:\/[\w.\-]+)?)(?=\s|$)/g

/** A message typed or pasted with "@repo" in it: the first mention of a known repo becomes the
 *  chat's repo and leaves the text. Unknown mentions stay as written. */
export function extractRepo(text: string, repos: Repo[]): { text: string; repo: Repo | null } {
  for (const m of text.matchAll(MENTION)) {
    const repo = findRepo(repos, m[2]!)
    if (repo) {
      const start = m.index + m[1]!.length
      const rest = (text.slice(0, start) + text.slice(start + 1 + m[2]!.length)).replace(/\s{2,}/g, ' ').trim()
      return { text: rest, repo }
    }
  }
  return { text: text.trim(), repo: null }
}
