/**
 * The landing page's hero: Otto fixing a GitHub issue (./scene.ts, all made up), as the events the
 * backend writes, each on a beat of a ~49s loop. The page feeds them through the app's own reducer
 * and renders the app's own components, so the replay is what Otto really looks like.
 *
 *   0–7s    the composer: "@acme/shop ", then # opens the issue picker; "disc" filters it; #12 is
 *           picked (its chip), and the message goes
 *   7–18s   the issue's card, Otto's steps (search, edit, 9 tests passed, push), its reply, and the
 *           proposal: "Closes #12"
 *   ~20s    a cursor clicks Create pull request   ·  ~22s  the PR card, Open
 *   ~23–28s CI: waiting, running, failed (tests); Fix CI appears
 *   ~30s    the cursor clicks Fix CI  ·  ~32–40s  Otto fixes the test and pushes to the PR
 *   ~40–44s CI again: waiting, running, passed ✓
 *   ~48s    fade, and again
 *
 * Nothing here touches the network: the page's buttons are pretend (Replay.tsx), and the events are
 * the script's.
 */
import { QueryClient } from '@tanstack/react-query'
import type { Issue } from '@/api/types'
import { keys } from '@/api/queries'
import type { SessionEvent } from '@/chat/reduce'
import { MODELS } from '@/fixtures/session.js'
import { filterIssues } from '@/utils/issue'
import {
  ALL_PASSING, BRANCH, ci, CI_DIFF, CLOSES, COMMIT_OUT, FIX_CI_DISPLAY, FIX_COMMIT, FIX_COMMIT_OUT, FIX_DIFF, FIX_INTRO,
  FIX_PUSH_OUT, FIX_REPLY, FIX_SHA, INTRO, ISSUE, ISSUE_CARD, ISSUES, PASSING, PR_BODY, PR_NUMBER, PR_TITLE, PR_URL,
  PUSH_OUT, REPLY, REPO, SEARCH_OUT, SHA, TASK, TYPED_QUERY, TYPED_REPO,
} from './scene'

/** The replay draws the app at this size, then scales it into its window. */
export const INNER_W = 1100
export const INNER_H = 620

/** The landing page's query cache: the app's components read the model catalog from it (the
 *  fixture's), and it never fetches: queries are off unless a component turns one on, and the
 *  replay's components don't. */
export function landingQueryClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false, refetchOnWindowFocus: false } } })
  qc.setQueryData(keys.models, MODELS)
  return qc
}

// --- the beats -------------------------------------------------------------------------------

/** The moments the page and its tests care about (ms into a loop). */
export const T = {
  typeRepo: 700, // "@acme/shop " (85ms a key)
  hash: 2_300, // "#": the issue picker opens with the 3 issues
  typeQuery: 3_700, // "disc" (170ms a key): the list narrows to 2
  move: 5_000, // the highlight moves to #12
  pick: 5_800, // #12's chip; the picker closes
  send: 7_000, // the message goes: the session starts
  intro: 8_300,
  diff: 11_600, // the edit's result: Changes shows the diff
  tests: 13_200,
  passed: 14_800, // 9 passed
  reply: 17_300,
  proposed: 18_000, // the proposal, "Closes #12"; Otto is done
  cursor: 19_800, // the cursor comes, and glides to Create pull request for ~1.3s
  click: 21_300,
  opened: 22_500, // the PR card: Open
  ciWaiting: 23_500,
  ciRunning: 25_000,
  ciFailed: 27_800, // CI failed · tests; Fix CI
  fixCursor: 29_600,
  fixClick: 31_100,
  fixing: 31_800, // Otto works again: "Fix CI: tests"
  fixDiff: 34_400,
  fixTests: 35_900,
  fixPassed: 37_300,
  updated: 39_500, // the push updated the PR; Otto is done
  ciRerun: 40_300,
  ciRerunning: 41_500,
  ciPassed: 44_000, // CI passed ✓
  fade: 48_000,
} as const
export const LOOP_MS = 49_500

const REPO_KEY_MS = 85
const QUERY_KEY_MS = 170
const CURSOR_STAYS_MS = 1_200 // after the click

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
const say = (at: number, content: string, working = true): Beat => [
  at, 'llm.message', { message: { role: 'assistant', content, ...(working ? { tool_calls: [{ id: `c${at}` }] } : {}) } },
]
const diffstat = { files: 1, additions: 1, deletions: 1 }

const BEATS: Beat[] = [
  // the message, with the issue's card (the gateway's first event for a message that names an issue)
  [T.send, 'session.created', { task: TASK, repo: REPO, model: MODELS.default_model }],
  [T.send, 'session.status', { status: 'running' }],
  [T.send, 'llm.message', { message: { role: 'user', content: `${TASK} (the issue, for the agent)` }, display: TASK, issue: ISSUE_CARD }],
  say(T.intro, INTRO),
  ...act(9_300, 10_000, 'code.search', { pattern: 'qualifies_for_bulk' }, ok({ stdout: SEARCH_OUT })),
  ...act(10_800, T.diff, 'fs.replace', { path: 'src/shop/pricing.py', old_str: '>', new_str: '>=' }, ok({ added: 1, removed: 1, diff: FIX_DIFF })),
  ...act(T.tests, T.passed, 'shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: PASSING })),
  ...act(15_400, 15_800, 'git.commit', { message: PR_TITLE }, ok({ stdout: COMMIT_OUT })),
  ...act(16_000, 16_600, 'git.push', {}, ok({ stderr: PUSH_OUT, branch: BRANCH, base: 'main', sha: SHA, diffstat })),
  say(T.reply, `${REPLY} Review the change, then create the pull request.`, false),
  [T.proposed, 'pr.proposed', {
    title: PR_TITLE, body: PR_BODY, head: BRANCH, base: 'main', ...diffstat,
    tests: { passed: 9, failed: 0, text: '9 passed' }, issues: CLOSES,
  }],
  [T.proposed, 'session.status', { status: 'done' }],
  [T.opened, 'pr.opened', { number: PR_NUMBER, html_url: PR_URL }],
  // CI on the pushed commit: one check fails
  [T.ciWaiting, 'ci.updated', ci.waiting(SHA)],
  [T.ciRunning, 'ci.updated', ci.running(SHA)],
  [T.ciFailed, 'ci.updated', ci.failed(SHA)],
  // Fix CI: a turn with the failing job's logs (the thread shows only the request)
  [T.fixing, 'session.status', { status: 'running' }],
  [T.fixing, 'llm.message', { message: { role: 'user', content: 'CI failed on GitHub… (the logs, for the agent)' }, display: FIX_CI_DISPLAY, ci_fix: { sha: SHA, checks: ['tests'] } }],
  say(32_700, FIX_INTRO),
  ...act(33_700, T.fixDiff, 'fs.replace', { path: 'tests/integration/test_checkout.py', old_str: '100.00', new_str: '90.00' }, ok({ added: 1, removed: 1, diff: CI_DIFF })),
  ...act(T.fixTests, T.fixPassed, 'shell.exec', { cmd: 'python -m pytest -q' }, ok({ stdout: ALL_PASSING })),
  ...act(37_800, 38_100, 'git.commit', { message: FIX_COMMIT }, ok({ stdout: FIX_COMMIT_OUT })),
  ...act(38_300, 38_800, 'git.push', {}, ok({ stderr: FIX_PUSH_OUT, branch: BRANCH, base: 'main', sha: FIX_SHA, diffstat })),
  say(39_300, FIX_REPLY, false),
  [T.updated, 'pr.updated', { number: PR_NUMBER, url: PR_URL, ...diffstat }],
  [T.updated, 'session.status', { status: 'done' }],
  // CI again, on the fix
  [T.ciRerun, 'ci.updated', ci.waiting(FIX_SHA)],
  [T.ciRerunning, 'ci.updated', ci.running(FIX_SHA)],
  [T.ciPassed, 'ci.updated', ci.passed(FIX_SHA)],
]

// --- frames ----------------------------------------------------------------------------------

/** The composer, as typed so far */
export type Draft = {
  /** the textarea's text */
  text: string
  /** the issue picker: open on this query, with this row highlighted */
  picker: { query: string; issues: Issue[]; active: number } | null
  /** the issue picked with # (its chip) */
  issue: Issue | null
  /** the message went: the composer is the chat's reply box */
  sent: boolean
}

export type Cursor = 'hidden' | 'start' | 'button'
export type Target = 'create' | 'fix'

export type Frame = {
  events: SessionEvent[]
  draft: Draft
  /** the workspace panel's tab: Changes while a diff is the news, else Terminal */
  tab: 'terminal' | 'changes'
  /** hidden; where it enters; on the target's button */
  cursor: Cursor
  /** the button the cursor goes for */
  target: Target | null
  /** the moment to press the target's button (once per loop) */
  click: Target | null
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

const typed = (text: string, t: number, from: number, keyMs: number) => text.slice(0, Math.max(0, Math.floor((t - from) / keyMs) + 1))

export function draftAt(t: number): Draft {
  if (t >= T.send) return { text: '', picker: null, issue: null, sent: true }
  if (t < T.typeRepo) return { text: '', picker: null, issue: null, sent: false }
  const repo = typed(TYPED_REPO, t, T.typeRepo, REPO_KEY_MS)
  if (t < T.hash) return { text: repo, picker: null, issue: null, sent: false }
  if (t >= T.pick) return { text: TYPED_REPO, picker: null, issue: ISSUE, sent: false }
  const query = t < T.typeQuery ? '' : typed(TYPED_QUERY, t, T.typeQuery, QUERY_KEY_MS)
  const issues = filterIssues(ISSUES, query)
  const active = t >= T.move ? Math.max(0, issues.indexOf(ISSUE)) : 0
  return { text: `${TYPED_REPO}#${query}`, picker: { query, issues, active }, issue: null, sent: false }
}

function cursorAt(t: number): Pick<Frame, 'cursor' | 'target' | 'click'> {
  for (const [target, appears, click, done] of [
    ['create', T.cursor, T.click, T.opened],
    ['fix', T.fixCursor, T.fixClick, T.fixing],
  ] as const) {
    if (t < appears || t >= click + CURSOR_STAYS_MS) continue
    return { cursor: t < appears + 300 ? 'start' : 'button', target, click: t >= click && t < done ? target : null }
  }
  return { cursor: 'hidden', target: null, click: null }
}

const changes = (t: number) => (t >= T.diff && t < T.tests) || (t >= T.fixDiff && t < T.fixTests)

/** The frame `elapsed` ms into the replay (any number of loops); loopStart: this loop's wall-clock start. */
export function frameAt(elapsed: number, loopStart: number): Frame {
  const t = ((elapsed % LOOP_MS) + LOOP_MS) % LOOP_MS
  return {
    events: eventsUntil(t, loopStart),
    draft: draftAt(t),
    tab: changes(t) ? 'changes' : 'terminal',
    ...cursorAt(t),
    fade: t >= T.fade,
  }
}

/** Reduced motion: the whole session, still: the PR with CI passed, no cursor, no fade. */
export function finalFrame(loopStart: number): Frame {
  return {
    events: eventsUntil(Infinity, loopStart),
    draft: draftAt(Infinity),
    tab: 'terminal',
    cursor: 'hidden',
    target: null,
    click: null,
    fade: false,
  }
}

export const loopOf = (elapsed: number) => Math.floor(elapsed / LOOP_MS)

// --- the clock -------------------------------------------------------------------------------

/** The replay's clock: it runs while the hero is on screen and the tab is visible, and a pause
 *  keeps its place. `since`: when it last started (null while paused); `banked`: ms played before. */
export type Clock = { since: number | null; banked: number }
export const stoppedClock: Clock = { since: null, banked: 0 }
export const elapsedOn = (c: Clock, now: number) => c.banked + (c.since === null ? 0 : now - c.since)
export const resume = (c: Clock, now: number): Clock => (c.since === null ? { since: now, banked: c.banked } : c)
export const pause = (c: Clock, now: number): Clock => (c.since === null ? c : { since: null, banked: elapsedOn(c, now) })
