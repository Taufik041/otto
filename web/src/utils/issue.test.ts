import type { Issue } from '@/api/types'
import { activeIssue, filterIssues, typedIssue } from './issue'

const issue = (number: number, title: string): Issue => ({ number, title, labels: [], updated_at: null })
const ISSUES = [issue(120, 'Crash on empty cart'), issue(7, 'Login button does nothing'), issue(12, 'Dark mode'), issue(31, 'Fix login on mobile')]

describe('the # being typed', () => {
  it('starts at a # at the start or after a space, up to the caret', () => {
    expect(activeIssue('#')).toEqual({ start: 0, end: 1, query: '' })
    expect(activeIssue('fix #log')).toEqual({ start: 4, end: 8, query: 'log' })
    expect(activeIssue('fix #12 now', 7)).toEqual({ start: 4, end: 7, query: '12' })
  })

  it('is not a # inside a word, or one already followed by a space', () => {
    expect(activeIssue('a#b')).toBeNull()
    expect(activeIssue('fix #12 ')).toBeNull()
    expect(activeIssue('fix it')).toBeNull()
  })
})

describe('filtering the picker', () => {
  it('by number (the exact one first) or by title, in any case', () => {
    expect(filterIssues(ISSUES, '12').map((i) => i.number)).toEqual([12, 120])
    expect(filterIssues(ISSUES, 'LOGIN').map((i) => i.number)).toEqual([7, 31])
    expect(filterIssues(ISSUES, '3').map((i) => i.number)).toEqual([31])
    expect(filterIssues(ISSUES, '')).toEqual(ISSUES)
    expect(filterIssues(ISSUES, 'nothing like it')).toEqual([])
  })
})

describe('a typed issue', () => {
  it('is "#12" or "issue #12", the first one only', () => {
    expect(typedIssue('fix #12')).toBe(12)
    expect(typedIssue('please fix issue #12 and #13')).toBe(12)
    expect(typedIssue('Issue #7: the login button')).toBe(7)
    expect(typedIssue('#31')).toBe(31)
    expect(typedIssue('(see #4)')).toBe(4)
  })

  it('is not a colour, a heading, an anchor or a number alone', () => {
    expect(typedIssue('make it #fff')).toBeNull()
    expect(typedIssue('# Heading')).toBeNull()
    expect(typedIssue('see page.html#12')).toBeNull()
    expect(typedIssue('fix 12 tests')).toBeNull()
    expect(typedIssue('#12abc')).toBeNull()
  })
})
