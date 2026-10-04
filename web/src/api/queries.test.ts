import { sessionsRefetchInterval } from './queries'
import { session } from '@/test/fixtures'

it('the chat list polls every 10s while a chat is working, and not otherwise', () => {
  expect(sessionsRefetchInterval([session({ attention: 'working' }), session({ id: 's2' })])).toBe(10_000)
  expect(sessionsRefetchInterval([session({ attention: 'done' }), session({ id: 's2', attention: null })])).toBe(false)
  expect(sessionsRefetchInterval(undefined)).toBe(false)
})
