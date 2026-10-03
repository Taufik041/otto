import type { DailyLimit } from './types'

/** A refused request: status 0 means the gateway couldn't be reached. */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  get dailyLimit(): DailyLimit | null {
    const b = this.body as Partial<DailyLimit> | null
    return this.status === 429 && b?.code === 'daily_limit' ? (b as DailyLimit) : null
  }
}

export const OFFLINE = "Can't reach Otto. Check your connection and try again."

/** FastAPI's {"detail": "..."} or a 422's [{msg, loc}], as one sentence. */
export function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const msg = (detail[0] as { msg?: unknown }).msg
    if (typeof msg === 'string') return msg.replace(/^Value error, /, '')
  }
  return fallback
}

export async function errorFrom(res: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // not JSON
  }
  return new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`.trim()), body)
}

/** A sentence to show for any error. */
export function messageOf(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? OFFLINE : capitalize(e.message)
  return 'Something went wrong. Try again.'
}

export function capitalize(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s
}
