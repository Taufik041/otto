import type { Issue } from '@/api/types'
import type { ActiveMention } from './mention'

/** The "#query" being typed: from a # at the start or after whitespace, up to the caret. */
const ISSUE_AT_CARET = /(^|\s)#([^\s#]*)$/

export function activeIssue(text: string, caret: number = text.length): ActiveMention | null {
  const m = ISSUE_AT_CARET.exec(text.slice(0, caret))
  if (!m) return null
  const start = m.index + m[1]!.length
  return { start, end: caret, query: m[2]! }
}

/** Issues whose number starts with the query, or whose title contains it (any case): numbers first. */
export function filterIssues(issues: Issue[], query: string): Issue[] {
  const q = query.trim().toLowerCase()
  if (!q) return issues
  // "#12" puts #12 itself first, then #120, #121…
  const byNumber = issues
    .filter((i) => String(i.number).startsWith(q))
    .sort((a, b) => Number(String(b.number) === q) - Number(String(a.number) === q))
  const byTitle = issues.filter((i) => !byNumber.includes(i) && i.title.toLowerCase().includes(q))
  return [...byNumber, ...byTitle]
}

const TYPED = /(?:^|[\s(])(?:issue\s+)?#(\d{1,9})(?![\w#])/i

/** The issue a typed "#12" or "issue #12" names (the first one: one issue per message), or null. */
export function typedIssue(text: string): number | null {
  const m = TYPED.exec(text)
  return m ? Number(m[1]) : null
}
