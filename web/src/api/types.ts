// Shapes of the gateway's JSON (gateway/*.py, http://localhost:8000/openapi.json).

export type Me = {
  id: string
  email: string | null
  name: string
  github_login: string | null
  avatar_url: string | null
  default_model: string | null
  daily_token_limit: number
  has_password: boolean
  created_at: string
}

/** /auth/login, /auth/signup, /auth/refresh, /me/password, /auth/reset */
export type TokenBody = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: Me
}

export type Model = {
  id: string
  label: string
  provider: string
  description?: string | null
  available: boolean
  hint?: string | null
}

export type Models = { default_model: string | null; models: Model[] }

export type Repo = {
  full_name: string
  private: boolean
  updated_at: string | null
  default_branch: string
  installation_id: number
}

export type SessionStatus =
  | 'pending'
  | 'provisioning'
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'interrupted'
  | 'stopped'
  | 'limited'

export type SessionSummary = {
  id: string
  title: string
  status: SessionStatus
  repo: string | null
  model: string | null
  pr_url: string | null
  updated_at: string
}

export type SessionDetail = SessionSummary & {
  task: string
  repo_url: string | null
  work_branch: string | null
  created_at: string
}

export type NewSession = { message: string; repo?: string | null; model?: string | null }
export type Created = { id: string; status: string; title: string; repo: string | null }

export type GitHubStatus = {
  connected: boolean
  login: string | null
  avatar_url: string | null
  installations: { id: number; account_login: string }[]
}

export type Unlinked = { id: number; uninstall_url: string }

export type Usage = {
  today: { tokens: number; limit: number; resets_at: string }
  month: { sessions: number; tokens: number; est_cost_usd: number }
  daily: { date: string; tokens: number }[]
  by_model: { model: string; tokens: number; est_cost_usd: number }[]
}

/** The 429 body when today's tokens are used up. */
export type DailyLimit = { code: 'daily_limit'; used: number; limit: number; resets_at: string }
