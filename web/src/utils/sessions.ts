import type { SessionStatus, SessionSummary } from '@/api/types'

export type GroupLabel = 'Today' | 'Yesterday' | 'Previous 7 days' | 'Older'
export type Group = { label: GroupLabel; sessions: SessionSummary[] }

const DAY = 24 * 60 * 60 * 1000

function localMidnight(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** How many calendar days (in the viewer's time zone) before `now` the moment was. */
export function daysAgo(iso: string, now: Date): number {
  return Math.round((localMidnight(now) - localMidnight(new Date(iso))) / DAY)
}

export function groupOf(iso: string, now: Date): GroupLabel {
  const d = daysAgo(iso, now)
  if (d <= 0) return 'Today'
  if (d === 1) return 'Yesterday'
  if (d <= 7) return 'Previous 7 days'
  return 'Older'
}

const ORDER: GroupLabel[] = ['Today', 'Yesterday', 'Previous 7 days', 'Older']

/** The sidebar's groups, in order, each newest first; empty groups are left out. */
export function groupSessions(sessions: SessionSummary[], now: Date = new Date()): Group[] {
  const sorted = [...sessions].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  const by = new Map<GroupLabel, SessionSummary[]>()
  for (const s of sorted) {
    const g = groupOf(s.updated_at, now)
    by.set(g, [...(by.get(g) ?? []), s])
  }
  return ORDER.filter((l) => by.has(l)).map((label) => ({ label, sessions: by.get(label)! }))
}

export type Dot = 'warn' | 'ok' | 'bad' | 'idle' | null

/** The status dot: working (amber), done (green), failed (red), stopped (gray); a plain chat has none. */
export function statusDot(s: Pick<SessionSummary, 'status' | 'repo'>): Dot {
  if (!s.repo) return null
  const map: Record<SessionStatus, Dot> = {
    pending: null,
    provisioning: 'warn',
    queued: 'warn',
    running: 'warn',
    done: 'ok',
    failed: 'bad',
    interrupted: 'bad',
    stopped: 'idle',
    limited: 'idle',
  }
  return map[s.status] ?? null
}
