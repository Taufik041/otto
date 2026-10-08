import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router'
import '../index.css'
import { ThemeProvider } from '../theme/ThemeProvider'
import { Landing, LandingNotFound } from './Landing'
import { seedCatalog } from './replay'

// the app's components it shows read their catalog from this cache; nothing is fetched from it
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
seedCatalog(queryClient)
const notFound = document.body.dataset.page === '404'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* the system's light or dark (the landing page has no switch); the favicon follows it */}
    <ThemeProvider fixed="system">
      <QueryClientProvider client={queryClient}>
        {/* the app's components link with the router; the landing page itself uses plain links */}
        <MemoryRouter>{notFound ? <LandingNotFound /> : <Landing />}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
