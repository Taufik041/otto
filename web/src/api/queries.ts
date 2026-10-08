import { useQuery } from '@tanstack/react-query'
import { api } from '.'
import type { SessionSummary } from './types'

export const keys = {
  me: ['me'] as const,
  health: ['health'] as const,
  models: ['models'] as const,
  repos: ['repos'] as const,
  github: ['github'] as const,
  usage: ['usage'] as const,
  sessions: ['sessions'] as const,
  session: (id: string) => ['sessions', id] as const,
}


/** Whether Otto's workers are up: checked every 30s (the gateway caches its own check as long). */
export const useHealth = () =>
  useQuery({ queryKey: keys.health, queryFn: api.health, staleTime: 15_000, refetchInterval: 30_000 })
export const useModels = () => useQuery({ queryKey: keys.models, queryFn: api.models, staleTime: 5 * 60_000 })
export const useRepos = () => useQuery({ queryKey: keys.repos, queryFn: api.repos, staleTime: 60_000 })
export const useGitHub = () => useQuery({ queryKey: keys.github, queryFn: api.github })
export const useUsage = () => useQuery({ queryKey: keys.usage, queryFn: api.usage })
export const useSession = (id: string) => useQuery({ queryKey: keys.session(id), queryFn: () => api.session(id) })

/** Poll the chat list every 10s while a chat is working (its dot changes when it ends); never otherwise. */
export function sessionsRefetchInterval(data: SessionSummary[] | undefined): number | false {
  return data?.some((s) => s.attention === 'working') ? 10_000 : false
}

/** The sidebar's chats: fresh on window focus, and polled while one is at work. */
export const useSessions = () =>
  useQuery({
    queryKey: keys.sessions,
    queryFn: api.sessions,
    refetchOnWindowFocus: true,
    refetchInterval: (q) => sessionsRefetchInterval(q.state.data as SessionSummary[] | undefined),
  })
