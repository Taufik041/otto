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
  deleteSession: (id: string) => client.request<{ id: string }>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

/** Start a GitHub flow: ask the gateway for the URL (it sets the state's cookie), then go there. */
export async function goToGitHub(get: () => Promise<{ url: string }>) {
  const { url } = await get()
  window.location.assign(url)
}
