import { setupServer } from 'msw/node'

/** MSW for every test: an unhandled request fails the test, so nothing reaches the network. */
export const server = setupServer()
export const API = 'http://localhost:8000'
