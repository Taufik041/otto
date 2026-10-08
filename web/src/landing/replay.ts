/**
 * The landing page's hero: the sample session (src/fixtures/session.js) as the events the backend
 * writes, each on a beat of a ~35s loop. The page feeds them through the app's own reducer and
 * renders the app's own components, so the replay is what Otto really looks like.
 *
 *   0s    the message          ·  ~3–8s  pytest (2 failed), search, read
 *   ~9s   the edit (diff)      ·  ~12s   pytest (9 passed), commit, push
 *   ~18s  the reply, "Ready for review"
 *   ~21s  a cursor comes, clicks Create pull request   ·  ~25s  "Pull request opened #9"
 *   ~33s  fade, and again
 */
import type { QueryClient } from '@tanstack/react-query'
import { keys } from '@/api/queries'
import type { SessionEvent } from '@/chat/reduce'
import {
  MODELS, BRANCH, COMMIT_OUT, FAILING, FIX_DIFF, INTRO, PASSING, PR_TITLE, PRICING_MD, PUSH_OUT, REPLY, REPO, SEARCH_OUT, TASK,
} from '@/fixtures/session.js'

/** The replay draws the app at this size, then scales it into its window. */
export const INNER_W = 1100
export const INNER_H = 620

/** The app's components read model labels from the query cache: the fixture catalog, so the
 *  landing page never asks the gateway for it. Call before the first render. */
export function seedCatalog(qc: QueryClient) {
  qc.setQueryData(keys.models, MODELS)
}

export const LOOP_MS = 35_000
export const PROPOSED_AT = 18_800
export const CURSOR_AT = 21_000 // the cursor appears; it glides to the button for ~1.3s
export const CLICK_AT = 23_000
export const OPENED_AT = 24_600
export const FADE_AT = 33_000
const CURSOR_GONE_AT = OPENED_AT + 1_200
const PR_NUMBER = 9
const PR_URL = `https://github.com/${REPO}/pull/${PR_NUMBER}`

type Beat = [at: number, type: string, payload: Record<string, unknown>]

const ok = (extra: Record<string, unknown> = {}) => ({ exit_code: 0, stdout: '', stderr: '', ...extra })
let n = 0
/** an action at `at`, and its result at `done` */
const act = (at: number, done: number, kind: string, args: Record<string, unknown>, result: Record<string, unknown>): Beat[] => {
  const id = `r${++n}`
  return [
    [at, 'bus.action', { action_id: id, kind, payload: args }],
    [done, 'bus.result', { action_id: id, ok: true, payload: result }],
  ]
}
const reply = `${REPLY} Review the change, then create the pull request.`

const BEATS: Beat[] = [
  [0, 'session.created', { task: TASK, repo: REPO, model: 'openrouter:openrouter/free' }],
  [0, 'session.status', { status: 'running' }],
  [0, 'llm.message', { message: { role: 'user', content: TASK } }],
  [1_200, 'llm.message', { message: { role: 'assistant', content: INTRO, tool_calls: [{ id: 'c' }] } }],
  ...act(2_600, 4_300, 'shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 1, stdout: FAILING, stderr: '' }),
  ...act(5_300, 6_200, 'code.search', { pattern: 'qualifies_for_bulk' }, ok({ stdout: SEARCH_OUT })),
  ...act(7_000, 7_900, 'fs.read', { path: 'docs/PRICING.md', start_line: 1, end_line: 12 }, ok({ stdout: PRICING_MD })),
  ...act(9_000, 11_000, 'fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, ok({ added: 1, removed: 1, diff: FIX_DIFF })),
  ...act(12_200, 14_000, 'shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: PASSING })),
  ...act(15_000, 15_500, 'git.commit', { message: PR_TITLE }, ok({ stdout: COMMIT_OUT })),
  ...act(16_000, 16_800, 'git.push', {}, ok({ stderr: PUSH_OUT, branch: BRANCH, base: 'main', diffstat: { files: 1, additions: 1, deletions: 1 } })),
  [17_800, 'llm.message', { message: { role: 'assistant', content: reply } }],
  [PROPOSED_AT, 'pr.proposed', {
    title: PR_TITLE, body: REPLY, head: BRANCH, base: 'main', additions: 1, deletions: 1, files: 1,
    tests: { passed: 9, failed: 0, text: '9 passed' },
  }],
  [PROPOSED_AT, 'session.status', { status: 'done' }],
  [OPENED_AT, 'pr.opened', { number: PR_NUMBER, html_url: PR_URL }],
]

export type Frame = {
  events: SessionEvent[]
  /** the workspace panel's tab: Changes while the diff is the news, else Terminal */
  tab: 'terminal' | 'changes'
  /** hidden; where it enters; on the Create button */
  cursor: 'hidden' | 'start' | 'button'
  /** the moment to press Create pull request (once per loop) */
  click: boolean
  fade: boolean
}

function eventsUntil(t: number, loopStart: number): SessionEvent[] {
  return BEATS.filter(([at]) => at <= t).map(([at, type, payload], i) => ({
    seq: i + 1,
    ts: new Date(loopStart + at).toISOString(),
    type,
    payload,
  }))
}

/** The frame `elapsed` ms into the replay (any number of loops); loopStart: this loop's wall-clock start. */
export function frameAt(elapsed: number, loopStart: number): Frame {
  const t = ((elapsed % LOOP_MS) + LOOP_MS) % LOOP_MS
  return {
    events: eventsUntil(t, loopStart),
    tab: t >= 11_000 && t < 14_000 ? 'changes' : 'terminal',
    cursor: t < CURSOR_AT || t >= CURSOR_GONE_AT ? 'hidden' : t < CURSOR_AT + 300 ? 'start' : 'button',
    click: t >= CLICK_AT && t < OPENED_AT,
    fade: t >= FADE_AT,
  }
}

/** Reduced motion: the whole session, still: the opened PR, no cursor, no fade. */
export function finalFrame(loopStart: number): Frame {
  return { events: eventsUntil(Infinity, loopStart), tab: 'terminal', cursor: 'hidden', click: false, fade: false }
}

export const loopOf = (elapsed: number) => Math.floor(elapsed / LOOP_MS)
