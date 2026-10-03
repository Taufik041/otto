import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { LAYER } from '@/components/layers'
import { renderSignedIn } from '@/test/render'
import { API, server } from '@/test/server'
import { ProfileMenu } from './Sidebar'

beforeEach(() => {
  server.use(http.get(`${API}/sessions`, () => HttpResponse.json([])))
})

it.each([
  ['a click', async (b: HTMLElement) => userEvent.click(b)],
  ['Enter', async (b: HTMLElement) => (b.focus(), userEvent.keyboard('{Enter}'))],
  ['Space', async (b: HTMLElement) => (b.focus(), userEvent.keyboard(' '))],
])('%s opens the profile menu: Settings, Usage, Theme, Sign out', async (_, open) => {
  renderSignedIn(<ProfileMenu />)
  await open(screen.getByRole('button', { name: 'Account menu' }))

  const menu = await screen.findByRole('menu')
  expect(screen.getByRole('menuitem', { name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Usage' })).toBeInTheDocument()
  expect(screen.getByRole('radiogroup', { name: 'Theme' })).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument()
  // drawn above the sidebar (and the mobile drawer) it opens over
  expect(menu.style.zIndex).toBe(String(LAYER.menu))
})

it('Settings navigates to /settings', async () => {
  renderSignedIn(<ProfileMenu />)
  await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Settings' }))
  await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/settings/account'))
})

it('the collapsed rail opens the same menu', async () => {
  renderSignedIn(<ProfileMenu compact />)
  await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
  expect(await screen.findByRole('menuitem', { name: 'Settings' })).toBeInTheDocument()
})

it('menus stack above the sidebar and the drawer, below dialogs', () => {
  expect(LAYER.menu).toBeGreaterThan(LAYER.sidebar)
  expect(LAYER.sidebar).toBeGreaterThan(LAYER.scrim)
  expect(LAYER.dialog).toBeGreaterThan(LAYER.menu)
})
