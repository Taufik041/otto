// The CI row's words (CiRow.tsx): GitHub's CI for the commit Otto pushed last.
import { firstFailing, type Ci, type CiCheck } from './reduce'

export type Tone = 'working' | 'ok' | 'bad' | 'muted'

export const TONE: Record<Tone, string> = { working: 'text-accent', ok: 'text-ok', bad: 'text-bad', muted: 'text-muted' }

/** CI queued or running with no change for this long: "CI status unknown" (the gateway agrees) */
export const STALE_MS = 2 * 60 * 60 * 1000

export function ciStale(ci: Ci, now: number): boolean {
  return (ci.state === 'queued' || ci.state === 'running') && now - Date.parse(ci.updatedAt) >= STALE_MS
}

const checks = (n: number) => `${n} ${n === 1 ? 'check' : 'checks'}`

/** The row's words and colour: blue while CI works, green when it passed, red when it failed. */
export function ciLabel(ci: Ci, now: number = Date.now()): { text: string; tone: Tone } {
  if (ciStale(ci, now)) return { text: 'CI status unknown', tone: 'muted' }
  const n = ci.checks.length
  switch (ci.state) {
    case 'queued':
      return { text: n ? `CI queued · ${checks(n)}` : 'Waiting for CI', tone: 'working' }
    case 'running':
      return { text: `CI running · ${checks(n)}`, tone: 'working' }
    case 'passed':
      return { text: 'CI passed', tone: 'ok' }
    case 'failed': {
      const first = firstFailing(ci)
      return { text: first ? `CI failed · ${first}` : 'CI failed', tone: 'bad' }
    }
    case 'cancelled':
      return { text: 'CI cancelled', tone: 'muted' }
    case 'none':
      return { text: ci.reason === 'unreadable' ? "Can't read CI for this repo" : 'No CI on this repo', tone: 'muted' }
  }
}

/** 65 → "1m 5s" */
export function duration(seconds: number | null): string | null {
  if (seconds === null) return null
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m ? `${m}m ${s}s` : `${s}s`
}

export function checkResult(c: CiCheck): { text: string; tone: Tone } {
  if (c.status !== 'completed') return { text: c.status === 'in_progress' ? 'Running' : 'Queued', tone: 'working' }
  switch (c.conclusion) {
    case 'success':
      return { text: 'Passed', tone: 'ok' }
    case 'neutral':
    case 'skipped':
      return { text: c.conclusion === 'skipped' ? 'Skipped' : 'Neutral', tone: 'muted' }
    case 'cancelled':
    case 'stale':
      return { text: 'Cancelled', tone: 'muted' }
    case 'timed_out':
      return { text: 'Timed out', tone: 'bad' }
    default:
      return { text: 'Failed', tone: 'bad' }
  }
}
