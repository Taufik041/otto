import { useQuery } from '@tanstack/react-query'
import { api } from '.'
import type { SessionSummary } from './types'

export const keys = {
  me: ['me'] as const,
  models: ['models'] as const,
  repos: ['repos'] as const,
  github: ['github'] as const,
  usage: ['usage'] as const,
  sessions: ['sessions'] as const,
  session: (id: string) => ['sessions', id] as const,
}

const WORKING = new Set(['provisioning', 'queued', 'running'])

export const useModels = () => useQuery({ queryKey: keys.models, queryFn: api.models, staleTime: 5 * 60_000 })
export const useRepos = () => useQuery({ queryKey: keys.repos, queryFn: api.repos, staleTime: 60_000 })
export const useGitHub = () => useQuery({ queryKey: keys.github, queryFn: api.github })
export const useUsage = () => useQuery({ queryKey: keys.usage, queryFn: api.usage })
export const useSession = (id: string) => useQuery({ queryKey: keys.session(id), queryFn: () => api.session(id) })

/** The sidebar's chats; polled while one is at work, so its dot changes when it finishes. */
export const useSessions = () =>
  useQuery({
    queryKey: keys.sessions,
    queryFn: api.sessions,
    refetchInterval: (q) => ((q.state.data as SessionSummary[] | undefined)?.some((s) => WORKING.has(s.status)) ? 5000 : false),
  })
