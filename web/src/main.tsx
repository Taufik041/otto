import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { client } from './api'
import { ApiError } from './api/errors'
import App from './App'
import './index.css'
import { ThemeProvider } from './theme/ThemeProvider'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // a 4xx won't change by asking again; a network blip might
      retry: (n, e) => n < 2 && (!(e instanceof ApiError) || e.status === 0 || e.status >= 500),
      refetchOnWindowFocus: false,
    },
  },
})

// signed out (here or by a failed refresh): forget everything cached for the last user
client.subscribe(() => {
  if (client.getState().status === 'signedOut') queryClient.clear()
})
void client.restore()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
