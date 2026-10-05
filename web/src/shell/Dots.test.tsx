import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { session } from '@/test/fixtures'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { Sidebar } from './Sidebar'

function list(attention: 'working' | 'done' | 'failed' | null) {
  server.use(http.get(`${API}/sessions`, () => HttpResponse.json([{ ...session({ id: 's1', title: 'A chat' }), attention }])))
  renderSignedIn(<Sidebar mobile={false} collapsed={false} onToggle={() => {}} onNavigate={() => {}} />)
}

const row = async () => (await screen.findByText('A chat')).closest('a')!

it.each([
  ['working', 'Working', 'var(--warn)'],
  ['done', 'Done', 'var(--ok)'],
  ['failed', 'Failed', 'var(--bad)'],
] as const)('attention %s is a dot (%s)', async (attention, label, color) => {
  list(attention)
  const dot = within(await row()).getByRole('img', { name: label })
  expect(dot.style.background).toBe(color)
})

it('no attention, no dot (seen, stopped, a plain chat at rest)', async () => {
  list(null)
  expect(within(await row()).queryByRole('img')).not.toBeInTheDocument()
})

it('a working dot pulses softly', async () => {
  list('working')
  expect(within(await row()).getByRole('img', { name: 'Working' })).toHaveClass('animate-pulse-dot')
})

it('with reduced motion it stays steady', async () => {
  const real = window.matchMedia
  window.matchMedia = ((q: string) => ({ ...real(q), matches: q.includes('prefers-reduced-motion') })) as typeof window.matchMedia
  try {
    list('working')
    expect(within(await row()).getByRole('img', { name: 'Working' })).not.toHaveClass('animate-pulse-dot')
  } finally {
    window.matchMedia = real
  }
})
