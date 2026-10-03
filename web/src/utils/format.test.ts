import { compact, initials, updatedAgo } from './format'

it('updatedAgo reads like the design', () => {
  const now = new Date('2026-10-01T12:00:00Z')
  expect(updatedAgo('2026-10-01T10:00:00Z', now)).toBe('updated 2h ago')
  expect(updatedAgo('2026-09-28T12:00:00Z', now)).toBe('updated 3d ago')
  expect(updatedAgo('2026-09-24T12:00:00Z', now)).toBe('updated 1w ago')
  expect(updatedAgo(null, now)).toBe('')
})

it('compact and initials', () => {
  expect(compact(412_000)).toBe('412k')
  expect(compact(1_500)).toBe('1.5k')
  expect(compact(999)).toBe('999')
  expect(initials('Taufik Khan')).toBe('TK')
  expect(initials('', 'me@x.com')).toBe('M')
})
