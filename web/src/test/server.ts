import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const API = 'http://localhost:8000'

/** GET /health: Otto up, workers online (a test overrides it for the offline states). */
export const healthy = () =>
  http.get(`${API}/health`, () => HttpResponse.json({ status: 'up', workers: 'online', version: 'test' }))

/** MSW for every test: an unhandled request fails the test, so nothing reaches the network. */
export const server = setupServer(healthy())
