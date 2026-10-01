import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { client } from '@/api'
import type { Me } from '@/api/types'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { me as defaultMe, tokenBody } from './fixtures'

export function Where() {
  const loc = useLocation()
  return <div data-testid="where">{loc.pathname + loc.search}</div>
}

/** Render signed in as `user` at `path`, with a fresh query cache and the app's providers. */
export function renderSignedIn(ui: ReactElement, { path = '/', user = defaultMe }: { path?: string; user?: Me } = {}) {
  client.signIn({ ...tokenBody('test-token'), user })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="*" element={<>{ui}<Where /></>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}
