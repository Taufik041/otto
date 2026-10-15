// Shapes of the gateway's JSON (gateway/*.py, http://localhost:8000/openapi.json).

/** GET /health (no sign-in): new accounts accepted ("up") or not ("paused"); whether the
 *  sandbox cluster answers. Offline, plain chats still work and repo tasks don't. */
export type Health = {
  status: 'up' | 'paused'
  workers: 'online' | 'offline'
  /** whether the gateway is connected to RabbitMQ (down: no chat can start or go on) */
  bus?: 'up' | 'down'
  version: string
  /** whether "Forgot password?" can email a link (false: production without email set up) */
  password_reset?: boolean
}

export type Me = {
  id: string
  email: string | null
  /** false: an email sign-up that hasn't opened its confirmation link (it can't chat yet) */
  email_verified?: boolean
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
  /** the sidebar's dot: Otto works, or a turn ended done/failed (or CI failed) since the user last saw the chat */
  attention: 'working' | 'done' | 'failed' | null
  /** the CI of Otto's latest push (null: nothing pushed; older gateways leave it out). unknown:
   *  queued or running with no change for 2 hours, so the list stops refreshing for it */
  ci?: 'queued' | 'running' | 'passed' | 'failed' | 'cancelled' | 'none' | 'unknown' | null
}

export type SessionDetail = SessionSummary & {
  task: string
  repo_url: string | null
  work_branch: string | null
  created_at: string
}

/** client_message_id: posting the same one again returns the chat the first post made */
export type NewSession = { message: string; repo?: string | null; model?: string | null; client_message_id?: string }
export type Created = { id: string; status: string; title: string; repo: string | null }

export type GitHubStatus = {
  connected: boolean
  login: string | null
  avatar_url: string | null
  /** uninstall_url: where on GitHub to uninstall the App from it (Otto can't) */
  installations: { id: number; account_login: string; uninstall_url: string }[]
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
