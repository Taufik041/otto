/**
 * A session's events → what the chat shows. Pure: the same events always give the same view, and
 * events can arrive in any batch (initial load, then live), deduped by seq.
 *
 * Every event kind the backend emits, and what becomes of it (see also web/README.md):
 *
 * | event                      | payload                                     | in the UI |
 * |----------------------------|---------------------------------------------|-----------|
 * | session.created            | {task, repo, model}                         | the first user message (repo chip); a turn starts |
 * | repo.attached              | {repo}                                      | the chat becomes an agent chat: later turns get work blocks |
 * | session.status             | {status}                                    | live / final state of the current turn; a new turn when work starts again |
 * | llm.message (system)       | {message}                                   | hidden |
 * | llm.message (user)         | {message}                                   | a user message (the task's own echo is merged) |
 * | llm.message (assistant)    | {message: {content, tool_calls?}}           | prose; before the first step it introduces the block, after it a note in the block; without tool calls it is the reply |
 * | llm.message (tool)         | {message}                                   | hidden (bus.result has the same, in full) |
 * | bus.action                 | {action_id, kind, payload}                  | a step (live until its result) |
 * | bus.result                 | {action_id, ok, payload}                    | the step's result; Changes (diffs, reads) and Terminal entries |
 * | pr.opened                  | {number, html_url}                          | the PR (card after the block) |
 * | usage.limit_reached        | {used, limit, resets_at}                    | the usage-limit card |
 * | error                      | {stage, message}                            | the error card with Retry (llm, sandbox setup); destroy_sandbox is hidden |
 * | llm.usage                  | {provider, model, tokens}                   | hidden |
 * | llm.key_rotated            | {provider, from_index, to_index, reason}    | hidden (infrastructure) |
 * | sandbox.reused / .recreated| {} / {previous}                             | hidden (infrastructure) |
 */

export type SessionEvent = { seq: number; ts: string; type: string; payload: Record<string, unknown> }

export type Status =
  | 'pending'
  | 'provisioning'
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'interrupted'
  | 'stopped'
  | 'limited'

export const ACTIVE: ReadonlySet<string> = new Set(['provisioning', 'queued', 'running'])

export type Tone = 'ok' | 'bad' | 'muted'
export type TestSummary = { passed: number; failed: number; errors: number; text: string; duration: string | null }

export type StepIcon = 'run' | 'search' | 'file' | 'edit' | 'push' | 'pr' | 'commit' | 'git'
export type Step = {
  id: string
  icon: StepIcon
  /** the design's red row for a model that stopped answering (from the turn's error event) */
  modelFailed?: boolean
  verb: string
  now: string
  code: string | null
  /** null while the step runs */
  ok: boolean | null
  /** the right-hand result: "9 passed", "2 matches", "lines 1–40", "failed" */
  res: { text: string; tone: Tone; strong?: boolean } | null
  add: number | null
  del: number | null
  sub: string | null
  /** opens the workspace panel here */
  target: { tab: 'changes'; path: string; entry: string } | { tab: 'terminal'; entry: string } | null
  tests: TestSummary | null
}

export type Note = { id: string; note: string }
export type BlockStatus = 'setup' | 'live' | 'done' | 'failed' | 'stopped' | 'paused'
export type WorkBlock = {
  id: string
  status: BlockStatus
  rows: (Step | Note)[]
  stepCount: number
  startedAt: string
  endedAt: string | null
  tests: TestSummary | null
  committed: boolean
}

export type PrCard = {
  id: string
  updated: boolean
  number: number
  url: string
  title: string | null
  repo: string
  branch: string | null
  base: string | null
  additions: number | null
  deletions: number | null
  files: number | null
  tests: TestSummary | null
  /** "See changes" opens the first edited file */
  firstFile: string | null
}

export type Item =
  | { kind: 'user'; id: string; text: string | null; repo: string | null }
  | { kind: 'prose'; id: string; text: string; avatar: boolean }
  | { kind: 'thinking'; id: string }
  | { kind: 'work'; id: string; block: WorkBlock; avatar: boolean }
  | { kind: 'pr'; id: string; pr: PrCard }
  | { kind: 'stopped'; id: string }
  | { kind: 'error'; id: string; title: string; message: string }
  | { kind: 'limit'; id: string; used: number; limit: number; resetsAt: string }
  | { kind: 'nudge'; id: string }
  /** the chat moved to another model from here on: a quiet divider */
  | { kind: 'model'; id: string; to: string }

export type FileEntry =
  | { id: string; type: 'diff'; diff: string; truncated: boolean }
  | { id: string; type: 'read'; start: number; text: string }
export type FileChange = {
  path: string
  kind: 'Created' | 'Edited' | 'Read'
  add: number
  del: number
  entries: FileEntry[]
}
export type TermEntry = {
  id: string
  cmd: string
  exit: number | null
  live: boolean
  stdout: string
  stderr: string
  tests: TestSummary | null
}

type PrRef = { number: number; url: string; title: string | null }

export type View = {
  lastSeq: number
  status: Status | null
  live: boolean
  repo: string | null
  model: string | null
  task: string | null
  items: Item[]
  files: FileChange[]
  terminal: TermEntry[]
  pr: { number: number; url: string; title: string | null } | null
  /** a new turn is starting and its user message hasn't arrived yet (a follow-up being set up) */
  awaitingUser: boolean
}

// --- the turn model --------------------------------------------------------------------------

type Action = { id: string; kind: string; args: Record<string, unknown>; ts: string; result?: Record<string, unknown>; ok?: boolean }

type Turn = {
  id: string
  user: { text: string | null; repo: string | null; confirmed: boolean } | null
  agent: boolean
  intro: string[]
  rows: ({ action: string } | Note)[]
  reply: string[]
  startedAt: string
  endedAt: string | null
  outcome: Status | null
  error: { stage: string; step: string | null; message: string } | null
  limit: { used: number; limit: number; resetsAt: string } | null
  stoppedHere: boolean
  /** a model switch that came with this turn's message */
  switchedTo: string | null
}

type State = {
  seen: Set<number>
  status: Status | null
  repo: string | null
  model: string | null
  task: string | null
  turns: Turn[]
  actions: Map<string, Action>
  /** set when work starts again after a final status, until we know if it's a retry or a follow-up */
  restart: { ts: string; afterFailure: boolean } | null
  prs: { number: number; url: string; turn: string }[]
  /** a model switch waiting for the turn it applies to */
  pendingModel: string | null
  /** every event folded in, by seq: a late gap is replayed from scratch */
  log: SessionEvent[]
}

export const emptyState = (): State => ({
  log: [],
  pendingModel: null,
  seen: new Set(),
  status: null,
  repo: null,
  model: null,
  task: null,
  turns: [],
  actions: new Map(),
  restart: null,
  prs: [],
})

const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {})

function newTurn(state: State, id: string, ts: string, user: Turn['user']): Turn {
  const t: Turn = {
    id,
    user,
    agent: state.repo !== null,
    intro: [],
    rows: [],
    reply: [],
    startedAt: ts,
    endedAt: null,
    outcome: null,
    error: null,
    limit: null,
    stoppedHere: false,
    switchedTo: state.pendingModel,
  }
  state.pendingModel = null
  state.turns.push(t)
  return t
}

const current = (s: State): Turn | undefined => s.turns[s.turns.length - 1]

/** The turn new work belongs to: a pending restart becomes a retry of the failed turn, or a new
 *  turn (a follow-up whose message we never saw). */
function workingTurn(s: State, ts: string, seq: number): Turn {
  const t = current(s)
  if (s.restart) {
    const r = s.restart
    s.restart = null
    if (r.afterFailure && t) {
      t.outcome = null
      t.endedAt = null
      t.error = null
      return t
    }
    return newTurn(s, `t${seq}`, r.ts, null)
  }
  return t ?? newTurn(s, `t${seq}`, ts, null)
}

/** Fold one event into the state (mutates; callers clone first). Unknown kinds are ignored. */
function apply(s: State, e: SessionEvent) {
  const p = e.payload ?? {}
  switch (e.type) {
    case 'session.created': {
      s.task = str(p.task)
      s.repo = str(p.repo)
      s.model = str(p.model)
      newTurn(s, `t${e.seq}`, e.ts, { text: s.task, repo: s.repo, confirmed: false })
      return
    }
    case 'session.model_changed': {
      const to = str(p.to)
      if (!to) return
      s.model = to
      s.pendingModel = to // shown with the message it came with
      return
    }
    case 'repo.attached': {
      s.repo = str(p.repo)
      const t = current(s)
      // a follow-up attached it: that turn (pending or not yet started) is the agent's
      if (s.restart) return
      if (t && t.outcome === null) t.agent = true
      return
    }
    case 'session.status': {
      const status = str(p.status) as Status | null
      if (!status) return
      const was = s.status
      s.status = status
      const t = current(s)
      if (ACTIVE.has(status)) {
        // work starts again after a final status: a follow-up or a retry, decided by what comes next
        if (t && t.outcome !== null && !s.restart) {
          s.restart = { ts: e.ts, afterFailure: t.outcome === 'failed' || t.outcome === 'interrupted' }
        }
        return
      }
      if (was === status) return
      if (s.restart) {
        // set up, then stopped or failed before any message or step: the pending turn ends here
        const r = s.restart
        s.restart = null
        if (r.afterFailure && t) {
          t.outcome = status
          t.endedAt = e.ts
          return
        }
        const nt = newTurn(s, `t${e.seq}`, r.ts, null)
        nt.outcome = status
        nt.endedAt = e.ts
        nt.stoppedHere = status === 'stopped'
        return
      }
      if (t && t.outcome === null) {
        t.outcome = status
        t.endedAt = e.ts
        t.stoppedHere = status === 'stopped'
      }
      return
    }
    case 'llm.message': {
      const m = rec(p.message)
      const role = str(m.role)
      const content = str(m.content)
      if (role === 'user') {
        const t = current(s)
        if (t?.user && !t.user.confirmed && t.user.text === content && t.outcome === null && !s.restart) {
          t.user.confirmed = true // the task's own echo
          return
        }
        const startedAt = s.restart?.ts ?? e.ts
        const attached = s.restart !== null && t !== undefined && s.repo !== null && !t.agent
        s.restart = null
        const nt = newTurn(s, `t${e.seq}`, startedAt, { text: content, repo: attached ? s.repo : null, confirmed: true })
        nt.agent = s.repo !== null
        return
      }
      if (role !== 'assistant') return // system prompts and tool results are not shown
      const t = workingTurn(s, e.ts, e.seq)
      const calls = Array.isArray(m.tool_calls) && m.tool_calls.length > 0
      const text = content?.trim()
      if (!text) return
      if (!calls) t.reply.push(text)
      else if (t.rows.length === 0) t.intro.push(text)
      else t.rows.push({ id: `n${e.seq}`, note: text })
      return
    }
    case 'bus.action': {
      const id = str(p.action_id)
      if (!id) return
      const t = workingTurn(s, e.ts, e.seq)
      s.actions.set(id, { id, kind: str(p.kind) ?? '', args: rec(p.payload), ts: e.ts })
      t.rows.push({ action: id })
      return
    }
    case 'bus.result': {
      const a = s.actions.get(str(p.action_id) ?? '')
      if (!a) return
      const r = rec(p.payload)
      a.result = r
      a.ok = p.ok === true && (num(r.exit_code) ?? 1) === 0
      return
    }
    case 'pr.opened': {
      const n = num(p.number)
      const url = str(p.html_url)
      const t = current(s)
      if (n !== null && url && t) s.prs.push({ number: n, url, turn: t.id })
      return
    }
    case 'usage.limit_reached': {
      const t = workingTurn(s, e.ts, e.seq)
      t.limit = { used: num(p.used) ?? 0, limit: num(p.limit) ?? 0, resetsAt: str(p.resets_at) ?? '' }
      return
    }
    case 'error': {
      const stage = str(p.stage) ?? ''
      if (stage === 'destroy_sandbox') return // tearing a sandbox down: not the user's concern
      const t = s.restart?.afterFailure ? current(s) : s.restart ? workingTurn(s, e.ts, e.seq) : current(s)
      if (t) t.error = { stage, step: str(p.step), message: str(p.message) ?? '' }
      return
    }
    default:
      return // llm.usage, llm.key_rotated, sandbox.*: infrastructure, never shown
  }
}

// --- results → steps --------------------------------------------------------------------------

const WORKSPACE = /^(?:\/workspace\/|\.\/)/

export function relPath(p: string): string {
  return p.replace(WORKSPACE, '')
}

const SUMMARY = /(\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|deselected|warnings?)(?:, \d+ \w+)*) in ([\d.]+s)/g

/** pytest's closing line ("2 failed, 7 passed in 0.12s"), if the output has one. */
export function testSummary(output: string): TestSummary | null {
  let last: RegExpExecArray | null = null
  for (const m of output.matchAll(SUMMARY)) last = m
  if (!last) return null
  const count = (word: RegExp) => {
    const m = last![1]!.match(new RegExp(`(\\d+) ${word.source}`))
    return m ? Number(m[1]) : 0
  }
  const passed = count(/passed/)
  const failed = count(/failed/)
  const errors = count(/errors?/)
  const parts = [failed && `${failed} failed`, errors && `${errors} ${errors === 1 ? 'error' : 'errors'}`, `${passed} passed`]
  return { passed, failed, errors, text: parts.filter(Boolean).join(', '), duration: `in ${last[2]}` }
}

function matches(stdout: string): string[] {
  return stdout.split('\n').filter((l) => /^[^:\s][^:]*:\d+:/.test(l))
}

function firstLine(s: string | null): string | null {
  const l = s?.split('\n').find((x) => x.trim())
  return l ? l.trim().slice(0, 200) : null
}

function shellQuote(s: string): string {
  return /^[\w@%+=:,./-]+$/.test(s) ? s : `"${s.replace(/(["\\$`])/g, '\\$1')}"`
}

/** The command a non-shell action ran, as the runner runs it (only real commands). */
function commandOf(a: Action): string | null {
  switch (a.kind) {
    case 'shell.exec':
      return str(a.args.cmd)
    case 'code.search':
      return `rg -n -- ${shellQuote(str(a.args.pattern) ?? '')}`
    case 'git.status':
      return 'git status'
    case 'git.diff':
      return 'git diff'
    case 'git.commit':
      return `git add -A && git commit -m ${shellQuote(str(a.args.message) ?? '')}`
    case 'git.push':
      return `git push -u origin ${str(a.result?.branch) ?? 'HEAD'}`
    default:
      return null // reads and edits show in Changes; the PR is an API call, not a command
  }
}

type Ctx = { live: boolean; prKnown: number | null }

function stepOf(a: Action, ctx: Ctx): Step {
  const r = a.result
  const done = r !== undefined
  const ok = done ? a.ok === true : null
  const path = relPath(str(a.args.path) ?? '')
  const failed: Step['res'] = { text: 'failed', tone: 'bad' }
  const base: Step = {
    id: a.id,
    icon: 'git',
    verb: a.kind,
    now: a.kind,
    code: null,
    ok,
    res: null,
    add: null,
    del: null,
    sub: null,
    target: null,
    tests: null,
  }
  const stderr = done ? firstLine(str(r!.stderr)) : null
  switch (a.kind) {
    case 'shell.exec': {
      const out = done ? `${str(r!.stdout) ?? ''}\n${str(r!.stderr) ?? ''}` : ''
      const tests = done ? testSummary(out) : null
      const exit = done ? num(r!.exit_code) : null
      return {
        ...base,
        icon: 'run',
        verb: 'Ran',
        now: 'Running',
        code: str(a.args.cmd),
        tests,
        res: tests
          ? { text: tests.text, tone: tests.failed || tests.errors ? 'bad' : 'ok', strong: true }
          : done && !ok
            ? { text: exit === null ? 'failed' : `exit ${exit}`, tone: 'bad' }
            : null,
        target: { tab: 'terminal', entry: a.id },
      }
    }
    case 'code.search': {
      const hits = done ? matches(str(r!.stdout) ?? '') : []
      return {
        ...base,
        icon: 'search',
        verb: 'Searched',
        now: 'Searching',
        code: str(a.args.pattern),
        res: !done ? null : ok ? { text: `${hits.length} ${hits.length === 1 ? 'match' : 'matches'}`, tone: 'muted' } : failed,
        sub: ok && hits.length ? hits.slice(0, 3).map((h) => h.split(':').slice(0, 2).join(':')).join(' · ') : stderr,
        target: { tab: 'terminal', entry: a.id },
      }
    }
    case 'fs.read': {
      const start = num(a.args.start_line)
      const end = num(a.args.end_line)
      return {
        ...base,
        icon: 'file',
        verb: 'Read',
        now: 'Reading',
        code: path,
        res: !done ? null : ok ? (start ? { text: `lines ${start}–${end ?? start + 200}`, tone: 'muted' } : null) : failed,
        sub: ok ? null : stderr,
        target: ok ? { tab: 'changes', path, entry: a.id } : null,
      }
    }
    case 'fs.replace':
    case 'fs.write': {
      const created = r?.created === true
      const write = a.kind === 'fs.write'
      return {
        ...base,
        icon: 'edit',
        verb: write ? (created ? 'Created' : 'Wrote') : 'Edited',
        now: write ? (done ? (created ? 'Creating' : 'Writing') : 'Writing') : 'Editing',
        code: path,
        add: ok ? num(r!.added) : null,
        del: ok ? num(r!.removed) : null,
        res: done && !ok ? failed : null,
        sub: ok ? null : stderr,
        target: ok ? { tab: 'changes', path, entry: a.id } : null,
      }
    }
    case 'git.status':
      return { ...base, verb: 'Checked git status', now: 'Checking git status', res: done && !ok ? failed : null, target: { tab: 'terminal', entry: a.id } }
    case 'git.diff':
      return { ...base, verb: 'Reviewed the diff', now: 'Reviewing the diff', res: done && !ok ? failed : null, target: { tab: 'terminal', entry: a.id } }
    case 'git.commit':
      return {
        ...base,
        icon: 'commit',
        verb: 'Committed',
        now: 'Committing',
        code: str(a.args.message),
        res: done && !ok ? failed : null,
        sub: ok ? null : stderr,
        target: { tab: 'terminal', entry: a.id },
      }
    case 'git.push': {
      const branch = str(r?.branch)
      const toPr = ctx.prKnown !== null
      return {
        ...base,
        icon: 'push',
        verb: toPr ? 'Pushed to pull request' : 'Pushed',
        now: toPr ? 'Pushing to pull request' : 'Pushing',
        code: toPr ? `#${ctx.prKnown}` : branch,
        res: done && !ok ? failed : null,
        sub: ok ? null : stderr,
        target: { tab: 'terminal', entry: a.id },
      }
    }
    case 'git.open_pr': {
      const n = num(r?.number)
      return {
        ...base,
        icon: 'pr',
        verb: 'Opened pull request',
        now: 'Opening pull request',
        code: ok && n !== null ? `#${n}` : null,
        res: done && !ok ? failed : null,
        sub: ok ? null : stderr,
      }
    }
    default:
      return { ...base, verb: `Ran ${a.kind}`, now: `Running ${a.kind}`, res: done && !ok ? failed : null }
  }
}

// --- state → view ---------------------------------------------------------------------------

function blockStatus(t: Turn, steps: number): BlockStatus {
  if (t.outcome === null) return steps ? 'live' : 'setup'
  if (t.outcome === 'done') return 'done'
  if (t.outcome === 'stopped') return 'stopped'
  if (t.outcome === 'limited') return 'paused' // the daily limit: the limit card says why
  return 'failed'
}

/** The error card's sentence: plain language, never internals. */
// the gateway's stages for setting up a turn's sandbox and queueing it
const SETUP_STAGES = new Set(['create_sandbox', 'sandbox', 'enqueue'])
// the brain's end-of-turn finish: the step that failed
const FINISH_STEPS: Record<string, string> = {
  'git.commit': "Otto couldn't commit the changes.",
  'git.push': "Otto couldn't push to GitHub.",
  'git.open_pr': "Otto couldn't open the pull request.",
}

/** The error card: a title naming what failed, and what to do. Never internals. */
export function errorCopy(
  error: { stage: string; step: string | null; message: string } | null,
  outcome: Status | null,
  committed: boolean,
): { title: string; message: string } {
  const resume = committed ? 'Retry to continue from the last step.' : 'Nothing was committed. Retry to continue from the last step.'
  if (error?.stage === 'llm') {
    const n = error.message.match(/after (\d+) attempts/)
    return {
      title: "Otto couldn't finish.",
      message: `${n ? `The model didn't respond after ${n[1]} tries.` : "The model didn't respond."} ${resume}`,
    }
  }
  if (error && SETUP_STAGES.has(error.stage)) return { title: "Otto couldn't set up the workspace.", message: 'Retry to try again.' }
  if (error?.stage === 'finish' && error.step && FINISH_STEPS[error.step])
    return { title: FINISH_STEPS[error.step]!, message: 'Retry to try again.' }
  if (!error && outcome === 'interrupted')
    return { title: 'Something went wrong.', message: `Otto was interrupted before it finished. ${resume}` }
  return { title: 'Something went wrong.', message: resume }
}

export function view(s: State): View {
  const items: Item[] = []
  const files = new Map<string, FileChange>()
  const terminal: TermEntry[] = []
  const live = s.status !== null && ACTIVE.has(s.status)
  let latestTests: TestSummary | null = null
  // the PR the session has so far; a holder, since TS narrows a let assigned in loops to never
  const known: { pr: PrRef | null } = { pr: null }
  let pushStat: { additions: number; deletions: number; files: number } | null = null
  let branch: string | null = null
  let base: string | null = null
  let firstEdited: string | null = null

  // work starting again: a retry reopens the failed turn; a follow-up gets a turn of its own
  // whose message we haven't seen yet (the chat shows what was just sent)
  const turns = s.turns.map((t, i) =>
    i === s.turns.length - 1 && live && s.restart?.afterFailure ? { ...t, outcome: null, endedAt: null, error: null } : t,
  )
  if (live && s.restart && !s.restart.afterFailure) {
    turns.push({
      id: 'pending',
      user: { text: null, repo: null, confirmed: true },
      agent: s.repo !== null,
      intro: [],
      rows: [],
      reply: [],
      startedAt: s.restart.ts,
      endedAt: null,
      outcome: null,
      error: null,
      limit: null,
      stoppedHere: false,
      switchedTo: s.pendingModel,
    })
  }

  for (const t of turns) {
    const ended = t.outcome !== null
    const turnLive = !ended && live
    if (t.switchedTo) items.push({ kind: 'model', id: `${t.id}-model`, to: t.switchedTo })
    if (t.user) items.push({ kind: 'user', id: `${t.id}-u`, text: t.user.text, repo: t.user.repo })
    let avatar = true
    const otto = () => {
      const a = avatar
      avatar = false
      return a
    }
    for (const [i, text] of t.intro.entries()) items.push({ kind: 'prose', id: `${t.id}-i${i}`, text, avatar: otto() })

    // the steps, merging a commit with the push right after it ("Committed and pushed")
    const rows: (Step | Note)[] = []
    let stepCount = 0
    let committed = false
    let opened: { number: number; url: string; title: string | null } | null = null
    let pushedToKnownPr = false
    let blockTests: TestSummary | null = null
    for (const row of t.rows) {
      if ('note' in row) {
        rows.push(row)
        continue
      }
      const a = s.actions.get(row.action)!
      const step = stepOf(a, { live: turnLive, prKnown: known.pr?.number ?? null })
      if (a.result === undefined && !turnLive) {
        step.ok = false
        step.res = { text: 'Stopped', tone: 'muted' }
      }
      const prev = rows[rows.length - 1]
      if (a.kind === 'git.push' && prev && 'icon' in prev && prev.icon === 'commit' && prev.ok) {
        prev.verb = known.pr ? 'Pushed to pull request' : 'Committed and pushed'
        prev.now = known.pr ? 'Pushing to pull request' : 'Committing and pushing'
        prev.icon = 'push'
        prev.code = step.code
        prev.ok = step.ok
        prev.res = step.res
        prev.sub = step.sub
        prev.target = step.target
      } else {
        rows.push(step)
        stepCount++
      }
      if (step.tests) {
        blockTests = step.tests
        latestTests = step.tests
      }
      const r = a.result
      if (a.ok && r) {
        if (a.kind === 'git.commit') committed = true
        if (a.kind === 'git.push') {
          branch = str(r.branch) ?? branch
          base = str(r.base) ?? base
          const d = rec(r.diffstat)
          if (num(d.files) !== null) pushStat = { files: num(d.files)!, additions: num(d.additions) ?? 0, deletions: num(d.deletions) ?? 0 }
          if (known.pr) pushedToKnownPr = true
        }
        if (a.kind === 'git.open_pr' && num(r.number) !== null && str(r.html_url)) {
          base = str(r.base) ?? base
          const title = str(r.title) ?? str(a.args.title)
          opened = { number: num(r.number)!, url: str(r.html_url)!, title }
        }
        if (a.kind === 'fs.replace' || a.kind === 'fs.write' || a.kind === 'fs.read') {
          const path = relPath(str(a.args.path) ?? '')
          const kind: FileChange['kind'] = a.kind === 'fs.read' ? 'Read' : r.created === true ? 'Created' : 'Edited'
          const f = files.get(path) ?? { path, kind, add: 0, del: 0, entries: [] }
          const rank = { Read: 0, Edited: 1, Created: 2 }
          if (rank[kind] > rank[f.kind]) f.kind = kind
          if (a.kind === 'fs.read') {
            f.entries.push({ id: a.id, type: 'read', start: num(a.args.start_line) ?? 1, text: str(r.stdout) ?? '' })
          } else {
            f.add += num(r.added) ?? 0
            f.del += num(r.removed) ?? 0
            if (str(r.diff)) f.entries.push({ id: a.id, type: 'diff', diff: str(r.diff)!, truncated: r.diff_truncated === true })
            firstEdited ??= path
          }
          files.set(path, f)
        }
      }
      const cmd = commandOf(a)
      if (cmd !== null) {
        const running = a.result === undefined
        terminal.push({
          id: a.id,
          cmd,
          exit: running ? null : num(a.result!.exit_code) ?? (a.ok ? 0 : 1),
          live: running && turnLive,
          stdout: str(a.result?.stdout) ?? '',
          stderr: str(a.result?.stderr) ?? '',
          tests: a.kind === 'shell.exec' && a.result ? testSummary(`${str(a.result.stdout) ?? ''}\n${str(a.result.stderr) ?? ''}`) : null,
        })
      }
    }

    // the model gave up mid-turn: the block ends with the design's red row
    if (t.error?.stage === 'llm' && (t.outcome === 'failed' || t.outcome === 'interrupted') && !live) {
      const tries = t.error.message.match(/after (\d+) attempts/)?.[1]
      rows.push({
        id: `${t.id}-llm`,
        icon: 'git',
        modelFailed: true,
        verb: 'Asked the model for the next step',
        now: 'Asking the model for the next step',
        code: null,
        ok: false,
        res: { text: 'No response', tone: 'bad', strong: true },
        add: null,
        del: null,
        sub: tries ? `${tries} tries` : null,
        target: null,
        tests: null,
      })
    }

    // a turn the daily limit stopped before it did anything: just the limit card
    const nothingDone = t.outcome === 'limited' && stepCount === 0
    if (t.agent && !nothingDone) {
      const status = blockStatus(t, stepCount)
      items.push({
        kind: 'work',
        id: `${t.id}-w`,
        avatar: otto(),
        block: { id: t.id, status, rows, stepCount, startedAt: t.startedAt, endedAt: t.endedAt, tests: blockTests, committed },
      })
    } else if (turnLive && t.reply.length === 0) {
      items.push({ kind: 'thinking', id: `${t.id}-thinking` })
    }

    if (t.stoppedHere) items.push({ kind: 'stopped', id: `${t.id}-stopped` })
    if ((t.outcome === 'failed' || t.outcome === 'interrupted') && !live) {
      items.push({ kind: 'error', id: `${t.id}-error`, ...errorCopy(t.error, t.outcome, committed) })
    }
    if (t.limit) items.push({ kind: 'limit', id: `${t.id}-limit`, used: t.limit.used, limit: t.limit.limit, resetsAt: t.limit.resetsAt })

    // the PR card: opened in this turn, or updated by a push to the PR an earlier turn opened
    const prOfTurn = opened ?? (pushedToKnownPr ? known.pr : null)
    if (prOfTurn && s.repo) {
      const updated = known.pr !== null && known.pr.number === prOfTurn.number
      items.push({
        kind: 'pr',
        id: `${t.id}-pr`,
        pr: {
          id: t.id,
          updated,
          number: prOfTurn.number,
          url: prOfTurn.url,
          title: prOfTurn.title ?? known.pr?.title ?? null,
          repo: s.repo,
          branch,
          base,
          additions: pushStat?.additions ?? null,
          deletions: pushStat?.deletions ?? null,
          files: pushStat?.files ?? null,
          tests: latestTests && !latestTests.failed && !latestTests.errors ? latestTests : null,
          firstFile: firstEdited,
        },
      })
    }
    const openedHere = opened as PrRef | null // assigned in the loop above; TS can't follow it
    if (openedHere) known.pr = { ...openedHere, title: openedHere.title ?? known.pr?.title ?? null }
    for (const [i, text] of t.reply.entries()) items.push({ kind: 'prose', id: `${t.id}-r${i}`, text, avatar: otto() })
  }

  // a PR opened without our seeing its action (older sessions): still known
  const lastPr = s.prs[s.prs.length - 1]
  if (!known.pr && lastPr) known.pr = { number: lastPr.number, url: lastPr.url, title: null }

  // a plain chat that has answered: the gentle nudge to mention a repo
  const last = items[items.length - 1]
  if (!s.repo && !live && last?.kind === 'prose') items.push({ kind: 'nudge', id: 'nudge' })

  return {
    lastSeq: Math.max(0, ...s.seen),
    status: s.status,
    live,
    repo: s.repo,
    model: s.model,
    task: s.task,
    items,
    // changed files first (as touched), then the ones only read
    files: [...files.values()].sort((a, b) => Number(a.kind === 'Read') - Number(b.kind === 'Read')),
    terminal,
    pr: known.pr,
    awaitingUser: s.restart !== null && !s.restart.afterFailure,
  }
}

/** Fold a batch of events in (any order, duplicates ignored). Returns a new state. */
export function reduce(prev: State, events: SessionEvent[]): State {
  const fresh = events.filter((e) => !prev.seen.has(e.seq)).sort((a, b) => a.seq - b.seq)
  if (fresh.length === 0) return prev
  const s: State = {
    ...prev,
    seen: new Set(prev.seen),
    turns: prev.turns.map((t) => ({ ...t, user: t.user && { ...t.user }, intro: [...t.intro], rows: [...t.rows], reply: [...t.reply] })),
    actions: new Map([...prev.actions].map(([k, a]) => [k, { ...a }])),
    restart: prev.restart && { ...prev.restart },
    prs: [...prev.prs],
  }
  // an event older than ones already folded in (a gap filled late) needs a full replay
  const maxSeen = Math.max(0, ...prev.seen)
  if (fresh[0]!.seq < maxSeen) return reduce(emptyState(), [...prev.log, ...fresh])
  for (const e of fresh) {
    s.seen.add(e.seq)
    apply(s, e)
  }
  s.log = [...prev.log, ...fresh]
  return s
}

export type { State }
