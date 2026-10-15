import { sessionsRefetchInterval } from './queries'
import { session } from '@/test/fixtures'

it('the chat list polls every 10s while a chat is working, and not otherwise', () => {
  expect(sessionsRefetchInterval([session({ attention: 'working' }), session({ id: 's2' })])).toBe(10_000)
  expect(sessionsRefetchInterval([session({ attention: 'done' }), session({ id: 's2', attention: null })])).toBe(false)
  expect(sessionsRefetchInterval(undefined)).toBe(false)
})

it('and every 30s while CI runs on a chat\'s push, so a failure turns its dot red', () => {
  expect(sessionsRefetchInterval([session({ ci: 'running' })])).toBe(30_000)
  expect(sessionsRefetchInterval([session({ ci: 'queued' })])).toBe(30_000)
  expect(sessionsRefetchInterval([session({ ci: 'running', attention: 'working' })])).toBe(10_000)
  expect(sessionsRefetchInterval([session({ ci: 'failed' }), session({ id: 's2', ci: 'none' })])).toBe(false)
})

it('never for a chat whose CI went unknown (no change for 2 hours)', () => {
  expect(sessionsRefetchInterval([session({ ci: 'unknown' }), session({ id: 's2', ci: 'passed' })])).toBe(false)
})
