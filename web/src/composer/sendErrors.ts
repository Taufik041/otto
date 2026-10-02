import { ApiError, capitalize, messageOf } from '@/api/errors'
import type { DailyLimit } from '@/api/types'

/** Why POST /sessions was refused, in the shape the composer shows it. */
export type SendProblem =
  | { kind: 'limit'; limit: DailyLimit }
  | { kind: 'busy'; message: string }
  | { kind: 'model'; message: string }
  | { kind: 'other'; message: string; title?: string }

const sentence = (s: string) => {
  const c = capitalize(s.trim())
  return /[.!?]$/.test(c) ? c : `${c}.`
}

export function sendProblem(e: unknown): SendProblem {
  if (e instanceof ApiError) {
    if (e.dailyLimit) return { kind: 'limit', limit: e.dailyLimit }
    // the per-user (MAX_ACTIVE_SESSIONS) and cluster (MAX_ACTIVE_SANDBOXES) caps
    if (e.status === 429) return { kind: 'busy', message: sentence(e.message) }
    // a follow-up while Otto works, or a second repo in one chat
    if (e.status === 409)
      return /wait until it finishes/.test(e.message)
        ? { kind: 'busy', message: 'Otto is still working on this chat. Wait until it finishes, or stop it.' }
        : { kind: 'other', title: "That message didn't go.", message: sentence(e.message) }
    // 503: no available default model; 422: the chosen one isn't available (any more)
    if (e.status === 503 || (e.status === 422 && /model/i.test(e.message)))
      return { kind: 'model', message: 'That model isn’t available right now. Pick another one and send again.' }
    if (e.status !== 0 && e.status < 500) return { kind: 'other', message: sentence(e.message) }
  }
  return { kind: 'other', message: messageOf(e) }
}
