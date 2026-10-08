export const MIN_OPEN_MS: number
export const MAX_MESSAGE: number
type Payload = { from: string; to: string[]; reply_to?: string; subject: string; text: string; html: string }
type Env = { RESEND_API_KEY?: string; OTTO_NOTIFY_TO?: string; EMAIL_FROM?: string }
export function resetLimits(): void
export function singleAddress(value: unknown): string | null
export function escapeHtml(s: string): string
export function wakeEmail(o: { email: string; message: string; page: string; userAgent: string; now: number }): { subject: string; text: string; html: string }
export function resendSend(payload: Payload, apiKey: string, fetchFn?: typeof fetch): Promise<void>
export function handleWake(request: Request, o: { env: Env; send: (p: Payload) => Promise<void>; now?: number; ip?: string }): Promise<Response>
export function logEmail(p: Payload): Promise<void>
