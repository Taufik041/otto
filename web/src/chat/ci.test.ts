import { ciLabel, ciStale, duration } from './ci'
import type { Ci, CiCheck } from './reduce'

const check = (name: string, conclusion: string | null = 'success', status = 'completed'): CiCheck => ({ name, status, conclusion, duration: 3, url: null })
const ci = (state: Ci['state'], checks: CiCheck[] = [], reason: string | null = null): Ci =>
  ({ sha: 'a', state, checks, url: null, reason, updatedAt: new Date().toISOString() })

it('the CI row says where CI is, in its colour', () => {
  expect(ciLabel(ci('queued'))).toEqual({ text: 'Waiting for CI', tone: 'working' })
  expect(ciLabel(ci('queued', [check('a', null, 'queued')]))).toEqual({ text: 'CI queued · 1 check', tone: 'working' })
  expect(ciLabel(ci('running', [check('a'), check('b', null, 'in_progress')]))).toEqual({ text: 'CI running · 2 checks', tone: 'working' })
  expect(ciLabel(ci('passed', [check('a')]))).toEqual({ text: 'CI passed', tone: 'ok' })
  expect(ciLabel(ci('failed', [check('lint'), check('tests', 'failure'), check('e2e', 'timed_out')]))).toEqual({ text: 'CI failed · tests', tone: 'bad' })
  expect(ciLabel(ci('cancelled', [check('a', 'cancelled')]))).toEqual({ text: 'CI cancelled', tone: 'muted' })
  expect(ciLabel(ci('none'))).toEqual({ text: 'No CI on this repo', tone: 'muted' })
  expect(ciLabel(ci('none', [], 'unreadable'))).toEqual({ text: "Can't read CI for this repo", tone: 'muted' })
})

it('durations read as minutes and seconds', () => {
  expect(duration(65)).toBe('1m 5s')
  expect(duration(9)).toBe('9s')
  expect(duration(null)).toBeNull()
})

it('queued or running with no change for 2 hours is "CI status unknown", grey; finished CI never is', () => {
  const at = Date.parse('2026-10-15T10:00:00Z')
  const running = { ...ci('running', [check('a', null, 'in_progress')]), updatedAt: '2026-10-15T10:00:00Z' }
  expect(ciLabel(running, at + 2 * 3600_000 - 1)).toEqual({ text: 'CI running · 1 check', tone: 'working' })
  expect(ciLabel(running, at + 2 * 3600_000)).toEqual({ text: 'CI status unknown', tone: 'muted' })
  expect(ciStale({ ...running, state: 'queued' }, at + 3 * 3600_000)).toBe(true)
  expect(ciStale({ ...running, state: 'failed' }, at + 30 * 3600_000)).toBe(false)
  expect(ciStale({ ...running, state: 'none' }, at + 30 * 3600_000)).toBe(false)
})
