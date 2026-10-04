import type { SessionEvent } from '@/chat/reduce'
import { createClient } from './client'
import type {
  Created,
  GitHubStatus,
  Me,
  Models,
  NewSession,
  Repo,
  SessionDetail,
  SessionSummary,
  TokenBody,
  Unlinked,
  Usage,
} from './types'

export const API_URL: string = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const client = createClient({ baseUrl: API_URL })

/** The WebSocket origin of the API: http(s) → ws(s). */
export const WS_URL = API_URL.replace(/^http/, 'ws').replace(/\/+$/, '')

const post = <T>(path: string, body?: unknown, retry?: boolean) =>
  client.request<T>(path, { method: 'POST', body, retry })

export const api = {
  async login(email: string, password: string) {
    client.signIn(await post<TokenBody>('/auth/login', { email, password }, false))
  },
  async signup(name: string, email: string, password: string) {
    client.signIn(await post<TokenBody>('/auth/signup', { name, email, password }, false))
  },
  forgot: (email: string) => post<{ ok: true }>('/auth/forgot', { email }, false),
  async reset(token: string, password: string) {
    client.signIn(await post<TokenBody>('/auth/reset', { token, password }, false))
  },
  /** Where to send the browser: GitHub sign-in ("signin") or linking it to this account ("link"). */
  githubUrl: (mode: 'signin' | 'link') => post<{ url: string }>('/auth/github/url', { mode }),
  installUrl: () => post<{ url: string }>('/github/install-url'),

  me: () => client.request<Me>('/me'),
  updateMe: (patch: { name?: string; default_model?: string | null }) =>
    client.request<Me>('/me', { method: 'PATCH', body: patch }),
  async changePassword(current: string, next: string) {
    client.signIn(await post<TokenBody>('/me/password', { current, new: next }))
  },
  deleteMe: () => client.request<{ ok: true }>('/me', { method: 'DELETE' }),

  models: () => client.request<Models>('/models'),
  repos: () => client.request<Repo[]>('/repos'),
  github: () => client.request<GitHubStatus>('/github'),
  unlinkInstallation: (id: number) => client.request<Unlinked>(`/github/installations/${id}`, { method: 'DELETE' }),
  usage: () => client.request<Usage>('/usage'),

  sessions: () => client.request<SessionSummary[]>('/sessions'),
  session: (id: string) => client.request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),
  createSession: (body: NewSession) => post<Created>('/sessions', body),
  events: (id: string, afterSeq = 0) =>
    client.request<SessionEvent[]>(`/sessions/${encodeURIComponent(id)}/events?after_seq=${afterSeq}`),
  wsTicket: (id: string) => post<{ ticket: string }>(`/sessions/${encodeURIComponent(id)}/ws-ticket`),
  followUp: (id: string, body: { text: string; repo?: string | null; model?: string | null }) =>
    post<{ id: string; status: string; repo: string | null }>(`/sessions/${encodeURIComponent(id)}/messages`, body),
  stop: (id: string) => post<{ id: string; status: string }>(`/sessions/${encodeURIComponent(id)}/stop`),
  /** the user saw the chat up to event `seq` (its finished turn stops wanting attention) */
  seen: (id: string, seq: number) => post<{ last_seen_seq: number }>(`/sessions/${encodeURIComponent(id)}/seen`, { seq }),
  /** open Otto's proposed pull request on GitHub (idempotent), or decline it for now */
  createPr: (id: string, title?: string) =>
    post<{ number: number; url: string; title: string; created: boolean }>(
      `/sessions/${encodeURIComponent(id)}/pr`,
      title ? { title } : undefined,
    ),
  declinePr: (id: string) => post<{ ok: true }>(`/sessions/${encodeURIComponent(id)}/pr/decline`),
  rename: (id: string, title: string) =>
    client.request<SessionSummary>(`/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', body: { title } }),
  retry: (id: string, model?: string) =>
    post<{ id: string; status: string }>(`/sessions/${encodeURIComponent(id)}/retry`, model ? { model } : undefined),
  deleteSession: (id: string) => client.request<{ id: string }>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

/** Start a GitHub flow: ask the gateway for the URL (it sets the state's cookie), then go there. */
export async function goToGitHub(get: () => Promise<{ url: string }>) {
  const { url } = await get()
  window.location.assign(url)
}
