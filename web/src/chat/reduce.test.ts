import { emptyState, errorMessage, reduce, testSummary, view, type Item, type SessionEvent, type Step } from './reduce'

/** Events built in order, like the backend writes them. */
function log() {
  const events: SessionEvent[] = []
  let seq = 0
  let t = Date.parse('2026-10-02T14:02:00Z')
  const add = (type: string, payload: Record<string, unknown> = {}) => {
    seq += 1
    t += 1000
    events.push({ seq, ts: new Date(t).toISOString(), type, payload })
    return api
  }
  let actionN = 0
  const api = {
    events,
    add,
    created: (task: string, repo: string | null = 'Taufik041/otto_test') =>
      add('session.created', { task, repo, model: 'openrouter:openrouter/free' }),
    status: (status: string) => add('session.status', { status }),
    msg: (role: string, content: string | null, tool_calls?: unknown[]) =>
      add('llm.message', { message: { role, content, ...(tool_calls ? { tool_calls } : {}) } }),
    /** an action and (unless result is null) its result */
    act: (kind: string, args: Record<string, unknown>, result: Record<string, unknown> | null = { exit_code: 0, stdout: '', stderr: '' }) => {
      const id = `a${++actionN}`
      add('bus.action', { action_id: id, kind, payload: args })
      if (result) add('bus.result', { action_id: id, ok: true, payload: result })
      return api
    },
  }
  return api
}

const v = (events: SessionEvent[]) => view(reduce(emptyState(), events))
const kinds = (items: Item[]) => items.map((i) => i.kind)
const work = (items: Item[]) => items.filter((i) => i.kind === 'work').map((i) => (i.kind === 'work' ? i.block : null)!)
const steps = (items: Item[], n = 0) => work(items)[n]!.rows.filter((r): r is Step => 'icon' in r)
const call = { id: 'c', type: 'function', function: { name: 'x', arguments: '{}' } }

const PYTEST_FAIL = '...F..F..\nFAILED tests/test_pricing.py::test_bulk\n2 failed, 7 passed in 0.12s\n'
const PYTEST_OK = '.........                                [100%]\n9 passed in 0.09s\n'
const DIFF = '--- a/src/inventory/pricing.py\n+++ b/src/inventory/pricing.py\n@@ -22,3 +22,3 @@\n def q(quantity):\n-    return quantity > 10\n+    return quantity >= 10\n'

/** The design's main run: tests fail, search, read, edit, tests pass, commit+push, PR. */
function mainRun() {
  return log()
    .created('two tests are failing, find out why and fix the source, not the tests')
    .status('provisioning')
    .status('queued')
    .status('running')
    .msg('system', 'You are Otto...')
    .msg('user', 'two tests are failing, find out why and fix the source, not the tests')
    .msg('assistant', "On it. I'll reproduce the failures first.", [call])
    .act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 1, stdout: PYTEST_FAIL, stderr: '' })
    .msg('tool', '{...}')
    .act('code.search', { pattern: 'qualifies_for_bulk' }, {
      exit_code: 0,
      stdout: 'src/inventory/pricing.py:22:def qualifies_for_bulk(q):\nsrc/inventory/legacy_pricing.py:15:def qualifies_for_bulk(qty):',
      stderr: '',
    })
    .act('fs.read', { path: '/workspace/docs/PRICING.md', start_line: 1, end_line: 12 }, { exit_code: 0, stdout: '# Pricing\n', stderr: '' })
    .act('fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, {
      exit_code: 0, stdout: 'replaced 1 occurrence', stderr: '', diff: DIFF, added: 1, removed: 1,
    })
    .act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 0, stdout: PYTEST_OK, stderr: '' })
    .act('git.commit', { message: 'Fix bulk discount threshold' })
    .act('git.push', {}, {
      exit_code: 0, stdout: '', stderr: '', branch: 'otto/4299fa2c3f', base: 'main',
      diffstat: { files: 1, additions: 1, deletions: 1 },
    })
    .act('git.open_pr', { title: 'Fix bulk discount threshold', body: 'b' }, {
      exit_code: 0, stdout: 'u', stderr: '', number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3',
      title: 'Fix bulk discount threshold', base: 'main',
    })
    .add('pr.opened', { number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3' })
    .msg('assistant', 'Found it. `qualifies_for_bulk` used `>` instead of `>=`.')
    .status('done')
}

describe('a run on a repo, start to PR', () => {
  it('shows the message, the intro, the block, the PR card and the reply, in order', () => {
    const view_ = v(mainRun().events)
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'work', 'pr', 'prose'])
    const [user, intro] = view_.items
    expect(user).toMatchObject({ kind: 'user', text: 'two tests are failing, find out why and fix the source, not the tests', repo: 'Taufik041/otto_test' })
    expect(intro).toMatchObject({ kind: 'prose', text: "On it. I'll reproduce the failures first.", avatar: true })
    expect(view_.status).toBe('done')
    expect(view_.live).toBe(false)
  })

  it('turns actions into the design steps, merging the commit with its push', () => {
    const s = steps(v(mainRun().events).items)
    expect(s.map((x) => [x.verb, x.code])).toEqual([
      ['Ran', 'python -m pytest -q'],
      ['Searched', 'qualifies_for_bulk'],
      ['Read', 'docs/PRICING.md'],
      ['Edited', 'src/inventory/pricing.py'],
      ['Ran', 'python -m pytest -q'],
      ['Committed and pushed', 'otto/4299fa2c3f'],
      ['Opened pull request', '#3'],
    ])
    expect(s[0]!.res).toEqual({ text: '2 failed, 7 passed', tone: 'bad', strong: true })
    expect(s[1]!.res).toEqual({ text: '2 matches', tone: 'muted' })
    expect(s[1]!.sub).toBe('src/inventory/pricing.py:22 · src/inventory/legacy_pricing.py:15')
    expect(s[2]!.res).toEqual({ text: 'lines 1–12', tone: 'muted' })
    expect([s[3]!.add, s[3]!.del]).toEqual([1, 1])
    expect(s[4]!.res).toEqual({ text: '9 passed', tone: 'ok', strong: true })
    expect(s[3]!.target).toEqual({ tab: 'changes', path: 'src/inventory/pricing.py', entry: 'a4' })
    expect(s[0]!.target).toEqual({ tab: 'terminal', entry: 'a1' })
  })

  it('the finished block: done, with its step count, tests and duration', () => {
    const [block] = work(v(mainRun().events).items)
    expect(block!.status).toBe('done')
    expect(block!.stepCount).toBe(7)
    expect(block!.tests?.text).toBe('9 passed')
    expect(block!.committed).toBe(true)
    expect(Date.parse(block!.endedAt!) - Date.parse(block!.startedAt)).toBeGreaterThan(0)
  })

  it('the PR card: title, number, repo, branch → base, diffstat, tests passed', () => {
    const pr = v(mainRun().events).items.find((i) => i.kind === 'pr')
    expect(pr).toMatchObject({
      kind: 'pr',
      pr: {
        updated: false, number: 3, title: 'Fix bulk discount threshold', repo: 'Taufik041/otto_test',
        branch: 'otto/4299fa2c3f', base: 'main', additions: 1, deletions: 1, files: 1,
        url: 'https://github.com/Taufik041/otto_test/pull/3', firstFile: 'src/inventory/pricing.py',
      },
    })
    expect(pr?.kind === 'pr' && pr.pr.tests?.passed).toBe(9)
  })

  it('Changes: edited files with their diffs, reads as line-numbered slices', () => {
    const { files } = v(mainRun().events)
    expect(files.map((f) => [f.path, f.kind, f.add, f.del])).toEqual([
      ['docs/PRICING.md', 'Read', 0, 0],
      ['src/inventory/pricing.py', 'Edited', 1, 1],
    ])
    expect(files[0]!.entries).toEqual([{ id: 'a3', type: 'read', start: 1, text: '# Pricing\n' }])
    expect(files[1]!.entries).toEqual([{ id: 'a4', type: 'diff', diff: DIFF, truncated: false }])
  })

  it('Terminal: every real command with its exit status; no PR "command"', () => {
    const { terminal } = v(mainRun().events)
    expect(terminal.map((e) => [e.cmd, e.exit])).toEqual([
      ['python -m pytest -q', 1],
      ['rg -n -- qualifies_for_bulk', 0],
      ['python -m pytest -q', 0],
      ['git add -A && git commit -m "Fix bulk discount threshold"', 0],
      ['git push -u origin otto/4299fa2c3f', 0],
    ])
    expect(terminal[2]!.tests).toMatchObject({ passed: 9, duration: 'in 0.09s' })
  })
})

describe('live states', () => {
  it('provisioning or starting shows only "Setting up workspace…"', () => {
    const l = log().created('fix it').status('provisioning')
    expect(work(v(l.events).items)[0]).toMatchObject({ status: 'setup', rows: [] })
    l.status('queued').status('running').msg('system', 'p').msg('user', 'fix it')
    const view_ = v(l.events)
    expect(work(view_.items)[0]!.status).toBe('setup')
    expect(kinds(view_.items)).toEqual(['user', 'work']) // the task's echo is not a second message
    expect(view_.live).toBe(true)
  })

  it('a step without its result is the live one', () => {
    const l = log().created('fix it').status('running').act('shell.exec', { cmd: 'pytest' }, null)
    const [block] = work(v(l.events).items)
    expect(block!.status).toBe('live')
    expect(steps(v(l.events).items)[0]).toMatchObject({ ok: null, verb: 'Ran', now: 'Running' })
    expect(v(l.events).terminal[0]).toMatchObject({ live: true, exit: null })
  })

  it('assistant text between steps is a note in the block', () => {
    const l = log().created('t').status('running').act('git.status', {}).msg('assistant', 'Now the tests.', [call])
    expect(work(v(l.events).items)[0]!.rows[1]).toEqual({ id: 'n5', note: 'Now the tests.' })
  })
})

describe('endings', () => {
  it('stopped: the block says so, the running step halts, and the note follows', () => {
    const l = log().created('t').status('running').act('shell.exec', { cmd: 'pytest' }, null).status('stopped')
    const view_ = v(l.events)
    expect(kinds(view_.items)).toEqual(['user', 'work', 'stopped'])
    expect(work(view_.items)[0]!.status).toBe('stopped')
    expect(steps(view_.items)[0]).toMatchObject({ ok: false, res: { text: 'Stopped', tone: 'muted' } })
  })

  it('an LLM error: the failed block and the error card in plain words', () => {
    const l = log().created('t').status('running').act('git.status', {})
      .add('error', { stage: 'llm', message: 'no usable LLM response after 6 attempts; last: rate limited' })
      .status('failed')
    const view_ = v(l.events)
    expect(kinds(view_.items)).toEqual(['user', 'work', 'error'])
    expect(work(view_.items)[0]!.status).toBe('failed')
    expect(view_.items[2]).toMatchObject({
      message: "The model didn't respond after 6 tries. Nothing was committed. Retry to continue from the last step.",
    })
  })

  it('a sandbox setup error never shows internals', () => {
    const l = log().created('t').status('provisioning')
      .add('error', { stage: 'create_sandbox', message: 'ApiException: k8s said 500' })
      .status('failed')
    const err = v(l.events).items.find((i) => i.kind === 'error')
    expect(err).toMatchObject({ message: "Otto couldn't set up the workspace. Retry to try again." })
    expect(JSON.stringify(v(l.events))).not.toContain('k8s')
  })

  it('interrupted is retryable too', () => {
    const l = log().created('t').status('running').status('interrupted')
    expect(v(l.events).items.find((i) => i.kind === 'error')).toMatchObject({ message: expect.stringMatching(/^Otto was interrupted/) })
  })

  it('the daily limit: the limit card', () => {
    const l = log().created('t').status('running')
      .add('usage.limit_reached', { used: 50000, limit: 50000, resets_at: '2026-10-03T00:00:00+00:00' })
      .status('limited')
    const view_ = v(l.events)
    expect(view_.items.find((i) => i.kind === 'limit')).toMatchObject({ used: 50000, limit: 50000 })
    expect(view_.items.some((i) => i.kind === 'error')).toBe(false)
  })
})

describe('retry and follow-ups', () => {
  function failed() {
    return log().created('t').status('running').act('git.status', {})
      .add('error', { stage: 'llm', message: 'no usable LLM response after 6 attempts' }).status('failed')
  }

  it('a retry continues the same block, and the error card goes away', () => {
    const l = failed().status('provisioning')
    let view_ = v(l.events)
    expect(work(view_.items)).toHaveLength(1)
    expect(work(view_.items)[0]!.status).toBe('live')
    expect(view_.items.some((i) => i.kind === 'error')).toBe(false)

    l.status('queued').status('running').act('shell.exec', { cmd: 'pytest' }, { exit_code: 0, stdout: PYTEST_OK, stderr: '' })
      .msg('assistant', 'Done.').status('done')
    view_ = v(l.events)
    expect(kinds(view_.items)).toEqual(['user', 'work', 'prose'])
    expect(work(view_.items)[0]!.stepCount).toBe(2)
  })

  it('a follow-up gets its own turn; the PR card says "updated"', () => {
    const l = mainRun().status('provisioning')
    let view_ = v(l.events)
    expect(view_.awaitingUser).toBe(true)
    expect(kinds(view_.items).slice(-2)).toEqual(['user', 'work']) // the pending turn: its text is the one just sent
    expect(view_.items.at(-2)).toMatchObject({ kind: 'user', text: null })

    l.status('queued').status('running').msg('user', 'also add a test for exactly 11 units')
      .act('fs.replace', { path: 'tests/test_pricing.py', old_str: 'a', new_str: 'b' }, { exit_code: 0, stdout: '', stderr: '', diff: '+x', added: 3, removed: 0 })
      .act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 0, stdout: '10 passed in 0.10s', stderr: '' })
      .act('git.commit', { message: 'Add test' })
      .act('git.push', {}, { exit_code: 0, stdout: '', stderr: '', branch: 'otto/4299fa2c3f', base: 'main', diffstat: { files: 2, additions: 4, deletions: 1 } })
      .msg('assistant', 'Added a test.').status('done')
    view_ = v(l.events)
    expect(view_.awaitingUser).toBe(false)
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'work', 'pr', 'prose', 'user', 'work', 'pr', 'prose'])
    expect(view_.items[5]).toMatchObject({ text: 'also add a test for exactly 11 units' })
    const second = steps(view_.items, 1)
    expect(second.map((s) => [s.verb, s.code])).toEqual([
      ['Edited', 'tests/test_pricing.py'],
      ['Ran', 'python -m pytest -q'],
      ['Pushed to pull request', '#3'],
    ])
    expect(view_.items[7]).toMatchObject({
      pr: { updated: true, number: 3, title: 'Fix bulk discount threshold', additions: 4, deletions: 1, files: 2 },
    })
    expect(view_.files.map((f) => f.path)).toContain('tests/test_pricing.py')
  })
})

describe('plain chats', () => {
  it('only messages: no work blocks; "thinking" while it answers; the nudge after', () => {
    const l = log().created('what is a closure?', null).status('queued').status('running')
    expect(kinds(v(l.events).items)).toEqual(['user', 'thinking'])
    l.msg('system', 'chat').msg('user', 'what is a closure?').msg('assistant', 'A function that remembers.').status('done')
    const view_ = v(l.events)
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'nudge'])
    expect(view_.items[0]).toMatchObject({ repo: null })
  })

  it('mentioning a repo later turns it into an agent chat', () => {
    const l = log().created('what is a closure?', null).status('running')
      .msg('user', 'what is a closure?').msg('assistant', 'A function.').status('done')
      .status('provisioning').add('repo.attached', { repo: 'Taufik041/otto_test' }).status('queued').status('running')
      .msg('system', 'agent').msg('user', 'now fix the tests')
      .act('shell.exec', { cmd: 'pytest' }, { exit_code: 0, stdout: '9 passed in 0.1s', stderr: '' })
    const view_ = v(l.events)
    expect(view_.repo).toBe('Taufik041/otto_test')
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'user', 'work'])
    expect(view_.items[2]).toMatchObject({ text: 'now fix the tests', repo: 'Taufik041/otto_test' })
  })
})

describe('hidden and robust', () => {
  it('infrastructure events never reach the view', () => {
    const base = mainRun().events
    const infra = log()
    for (const e of base) infra.add(e.type, e.payload)
    infra
      .add('sandbox.reused')
      .add('sandbox.recreated', { previous: 'finished' })
      .add('llm.key_rotated', { provider: 'openrouter', from_index: 0, to_index: 1, reason: 'rate_limited' })
      .add('llm.usage', { provider: 'openrouter', model: 'm', prompt_tokens: 10, completion_tokens: 2 })
      .add('error', { stage: 'destroy_sandbox', message: 'gone' })
      .add('something.new', { x: 1 })
    const a = v(base)
    const b = v(infra.events)
    expect(b.items).toEqual(a.items)
    expect(b.terminal).toEqual(a.terminal)
    expect(JSON.stringify(b)).not.toMatch(/sandbox|rotat|destroy/i)
  })

  it('dedupes by seq and accepts events in any order and batch', () => {
    const { events } = mainRun()
    const once = v(events)
    let s = reduce(emptyState(), events.slice(0, 10))
    s = reduce(s, events.slice(5, 20)) // overlap
    s = reduce(s, [...events.slice(20)].reverse())
    s = reduce(s, events) // all again
    expect(view(s).items).toEqual(once.items)
    expect(view(s).lastSeq).toBe(events.length)
    // a gap filled late is replayed in order
    const late = reduce(reduce(emptyState(), [...events.slice(0, 3), ...events.slice(4)]), [events[3]!])
    expect(view(late).items).toEqual(once.items)
  })

  it('a failed tool call shows as failed with its error line', () => {
    const l = log().created('t').status('running')
      .act('fs.replace', { path: 'a.py', old_str: 'x', new_str: 'y' }, { exit_code: 1, stdout: '', stderr: 'old_str not found in /workspace/a.py.' })
    const [step] = steps(v(l.events).items)
    expect(step).toMatchObject({ ok: false, res: { text: 'failed', tone: 'bad' }, sub: 'old_str not found in /workspace/a.py.', target: null })
    expect(v(l.events).files).toEqual([])
  })

  it('writes: Created for a new file', () => {
    const l = log().created('t').status('running')
      .act('fs.write', { path: 'n.py', content: 'x' }, { exit_code: 0, stdout: '', stderr: '', created: true, diff: '+x', added: 1, removed: 0 })
    expect(steps(v(l.events).items)[0]).toMatchObject({ verb: 'Created', code: 'n.py', add: 1, del: 0 })
    expect(v(l.events).files[0]).toMatchObject({ kind: 'Created' })
  })
})

describe('helpers', () => {
  it('testSummary reads pytest\'s last summary line', () => {
    expect(testSummary(PYTEST_FAIL)).toEqual({ passed: 7, failed: 2, errors: 0, text: '2 failed, 7 passed', duration: 'in 0.12s' })
    expect(testSummary('=== 9 passed, 1 warning in 0.31s ===')).toMatchObject({ text: '9 passed' })
    expect(testSummary('1 error in 0.2s')).toMatchObject({ errors: 1, text: '1 error, 0 passed' })
    expect(testSummary('hello')).toBeNull()
  })

  it('errorMessage stays plain', () => {
    expect(errorMessage('llm', 'boom', true)).toBe("The model didn't respond. Retry to continue from the last step.")
  })
})
