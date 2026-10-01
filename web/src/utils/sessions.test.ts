import { daysAgo, groupSessions, statusDot } from './sessions'
import { session } from '@/test/fixtures'

// local times, so the test holds in any time zone
const at = (y: number, mo: number, d: number, h = 12, mi = 0) => new Date(y, mo - 1, d, h, mi).toISOString()
const now = new Date(2026, 9, 1, 15, 0) // Oct 1, 15:00

describe('groupSessions', () => {
  it('groups by calendar day: Today, Yesterday, Previous 7 days, Older', () => {
    const list = [
      session({ id: 'old', updated_at: at(2026, 9, 1) }),
      session({ id: 'today-early', updated_at: at(2026, 10, 1, 0, 5) }),
      session({ id: 'yesterday-late', updated_at: at(2026, 9, 30, 23, 59) }),
      session({ id: 'week', updated_at: at(2026, 9, 24) }),
      session({ id: 'eight-days', updated_at: at(2026, 9, 23) }),
      session({ id: 'today-late', updated_at: at(2026, 10, 1, 14, 0) }),
      session({ id: 'two-days', updated_at: at(2026, 9, 29, 1, 0) }),
    ]

    const groups = groupSessions(list, now)

    expect(groups.map((g) => [g.label, g.sessions.map((s) => s.id)])).toEqual([
      ['Today', ['today-late', 'today-early']],
      ['Yesterday', ['yesterday-late']],
      ['Previous 7 days', ['two-days', 'week']],
      ['Older', ['eight-days', 'old']],
    ])
  })

  it('leaves out empty groups and handles no chats', () => {
    expect(groupSessions([], now)).toEqual([])
    expect(groupSessions([session({ updated_at: at(2026, 3, 1) })], now).map((g) => g.label)).toEqual(['Older'])
  })

  it('a time just after midnight is today, and a future clock skew is too', () => {
    expect(daysAgo(at(2026, 10, 1, 0, 0), now)).toBe(0)
    expect(groupSessions([session({ updated_at: at(2026, 10, 1, 16) })], now)[0]!.label).toBe('Today')
  })
})

describe('statusDot', () => {
  it('maps statuses to the design dots; plain chats have none', () => {
    expect(statusDot({ status: 'running', repo: 'a/b' })).toBe('warn')
    expect(statusDot({ status: 'queued', repo: 'a/b' })).toBe('warn')
    expect(statusDot({ status: 'done', repo: 'a/b' })).toBe('ok')
    expect(statusDot({ status: 'failed', repo: 'a/b' })).toBe('bad')
    expect(statusDot({ status: 'stopped', repo: 'a/b' })).toBe('idle')
    expect(statusDot({ status: 'done', repo: null })).toBeNull()
  })
})
