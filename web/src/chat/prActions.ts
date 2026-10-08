import { createContext } from 'react'
import { api } from '@/api'

/** What the proposal card's buttons do: the gateway's routes. The landing page's replay gives it
 *  its own (a pretend create), so the real card plays without a gateway. */
export type PrActions = {
  create: (sessionId: string) => Promise<unknown>
  decline: (sessionId: string) => Promise<unknown>
}

export const PrActionsContext = createContext<PrActions>({
  create: (id) => api.createPr(id),
  decline: (id) => api.declinePr(id),
})
