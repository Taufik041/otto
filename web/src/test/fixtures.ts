import type { Me, Model, Repo, SessionSummary, TokenBody } from '@/api/types'

export const me: Me = {
  id: 'u1',
  email: 'taufik@hey.com',
  name: 'Taufik Khan',
  github_login: 'Taufik041',
  avatar_url: null,
  default_model: null,
  daily_token_limit: 50000,
  has_password: true,
  created_at: '2026-09-01T10:00:00+00:00',
}

export const tokenBody = (access_token = 'tok-1', expires_in = 900): TokenBody => ({
  access_token,
  token_type: 'bearer',
  expires_in,
  user: me,
})

export const models: Model[] = [
  { id: 'openrouter:openrouter/free', label: 'OpenRouter Free', provider: 'openrouter',
    description: 'Free, good for small tasks', available: true, hint: null },
  { id: 'openai:gpt-4.1-mini', label: 'GPT-4.1 mini', provider: 'openai', description: 'Fast and capable',
    available: true, hint: null },
  { id: 'openai:gpt-4.1', label: 'GPT-4.1', provider: 'openai', description: 'Best for larger changes',
    available: false, hint: 'Unavailable right now. Try again later.' },
]

export const repos: Repo[] = [
  { full_name: 'Taufik041/otto_test', private: true, updated_at: '2026-10-01T08:00:00Z', default_branch: 'main', installation_id: 1 },
  { full_name: 'Taufik041/portfolio', private: false, updated_at: '2026-09-28T08:00:00Z', default_branch: 'main', installation_id: 1 },
  { full_name: 'Taufik041/petal', private: true, updated_at: '2026-09-24T08:00:00Z', default_branch: 'main', installation_id: 1 },
]

export const session = (over: Partial<SessionSummary>): SessionSummary => ({
  id: 's1',
  title: 'Fix failing pricing tests',
  status: 'done',
  repo: 'Taufik041/otto_test',
  model: 'openrouter:openrouter/free',
  pr_url: null,
  updated_at: '2026-10-01T09:00:00+00:00',
  attention: null,
  ...over,
})
