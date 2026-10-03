import { emptyState, errorCopy, reduce, testSummary, view, type Item, type SessionEvent, type Step } from './reduce'
import { call, DIFF, log, mainRun, PYTEST_FAIL, PYTEST_OK } from '@/test/events'

const v = (events: SessionEvent[]) => view(reduce(emptyState(), events))
const kinds = (items: Item[]) => items.map((i) => i.kind)
const work = (items: Item[]) => items.filter((i) => i.kind === 'work').map((i) => (i.kind === 'work' ? i.block : null)!)
const steps = (items: Item[], n = 0) => work(items)[n]!.rows.filter((r): r is Step => 'icon' in r)

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
      ['src/inventory/pricing.py', 'Edited', 1, 1], // changed files first
      ['docs/PRICING.md', 'Read', 0, 0],
    ])
    expect(files[0]!.entries).toEqual([{ id: 'a4', type: 'diff', diff: DIFF, truncated: false }])
    expect(files[1]!.entries).toEqual([{ id: 'a3', type: 'read', start: 1, text: '# Pricing\n' }])
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
    expect(work(view_.items)[0]!.stepCount).toBe(1) // the red row isn't a step
    expect(work(view_.items)[0]!.rows.at(-1)).toMatchObject({
      modelFailed: true, verb: 'Asked the model for the next step', res: { text: 'No response' }, sub: '6 tries',
    })
    expect(view_.items[2]).toMatchObject({
      title: "Otto couldn't finish.",
      message: "The model didn't respond after 6 tries. Nothing was committed. Retry to continue from the last step.",
    })
  })

  it('a sandbox setup error never shows internals', () => {
    const l = log().created('t').status('provisioning')
      .add('error', { stage: 'create_sandbox', message: 'ApiException: k8s said 500' })
      .status('failed')
    const err = v(l.events).items.find((i) => i.kind === 'error')
    expect(err).toMatchObject({ title: "Otto couldn't set up the workspace.", message: 'Retry to try again.' })
    expect(JSON.stringify(v(l.events))).not.toContain('k8s')
  })

  it('interrupted is retryable too', () => {
    const l = log().created('t').status('running').status('interrupted')
    expect(v(l.events).items.find((i) => i.kind === 'error')).toMatchObject({
      title: 'Something went wrong.',
      message: expect.stringMatching(/^Otto was interrupted/),
    })
  })

  it('the daily limit: the limit card', () => {
    const l = log().created('t').status('running')
      .add('usage.limit_reached', { used: 50000, limit: 50000, resets_at: '2026-10-03T00:00:00+00:00' })
      .status('limited')
    const view_ = v(l.events)
    expect(view_.items.find((i) => i.kind === 'limit')).toMatchObject({ used: 50000, limit: 50000 })
    expect(view_.items.some((i) => i.kind === 'error')).toBe(false)
    expect(kinds(view_.items)).toEqual(['user', 'limit']) // it did nothing: no block

    const midway = log().created('t').status('running').act('git.status', {})
      .add('usage.limit_reached', { used: 50000, limit: 50000, resets_at: 'x' }).status('limited')
    expect(work(v(midway.events).items)[0]!.status).toBe('paused')
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

  it('errorCopy stays plain', () => {
    expect(errorCopy({ stage: 'llm', step: null, message: 'boom' }, 'failed', true)).toEqual({
      title: "Otto couldn't finish.",
      message: "The model didn't respond. Retry to continue from the last step.",
    })
  })
})

describe('the error card names what failed', () => {
  /** a turn that edited a file, then failed with this error event (or none) */
  function failedWith(error: Record<string, unknown> | null) {
    const l = log().created('fix it').status('running')
      .act('fs.replace', { path: 'a.py', old_str: 'x', new_str: 'y' }, { exit_code: 0, stdout: '', stderr: '', diff: '+y', added: 1, removed: 1 })
      .msg('assistant', 'Fixed.')
    if (error) l.add('error', error)
    l.status('failed')
    const card = v(l.events).items.find((i) => i.kind === 'error')
    expect(card).toBeDefined()
    return card as Extract<Item, { kind: 'error' }>
  }

  it.each([
    ['create_sandbox', "Otto couldn't set up the workspace."],
    ['sandbox', "Otto couldn't set up the workspace."],
    ['enqueue', "Otto couldn't set up the workspace."],
  ])('setup stage %s', (stage, title) => {
    expect(failedWith({ stage, message: 'ApiException: k8s 500' })).toMatchObject({ title, message: 'Retry to try again.' })
  })

  it.each([
    ['git.commit', "Otto couldn't commit the changes."],
    ['git.push', "Otto couldn't push to GitHub."],
    ['git.open_pr', "Otto couldn't open the pull request."],
  ])('finish step %s', (step, title) => {
    const card = failedWith({ stage: 'finish', step, message: `${step}: rejected by GitHub (token ghs_x)` })
    expect(card).toMatchObject({ title, message: 'Retry to try again.' })
    expect(JSON.stringify(card)).not.toMatch(/rejected|ghs_/) // never the raw error
  })

  it.each([
    ['a finish step with no copy of its own', { stage: 'finish', step: 'git.status', message: 'git.status: fatal' }],
    ['a finish error that names no step', { stage: 'finish', message: 'git.push: rejected' }],
    ['an unknown stage', { stage: 'something.new', message: 'boom' }],
    ['no error event at all', null],
  ])('anything else: %s', (_, error) => {
    // this turn edited but never committed, which the card says
    expect(failedWith(error)).toMatchObject({ title: 'Something went wrong.', message: 'Nothing was committed. Retry to continue from the last step.' })
  })

  it('every one offers Retry: the card is the error item, which always renders Retry', () => {
    expect(failedWith({ stage: 'finish', step: 'git.push', message: '' }).kind).toBe('error')
  })
})

describe('switching the model', () => {
  it('a model change is a divider before the message it applies to, and the chat\'s model follows', () => {
    const l = log().created('what is a closure?', null).status('running')
      .msg('user', 'what is a closure?').msg('assistant', 'A function.').status('done')
      .status('provisioning')
      .add('session.model_changed', { from: 'openrouter:openrouter/free', to: 'openai:gpt-4.1-mini' })
      .msg('user', 'and in Python?')
    let view_ = v(l.events)
    expect(view_.model).toBe('openai:gpt-4.1-mini')
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'model', 'user', 'thinking'])
    expect(view_.items[2]).toMatchObject({ kind: 'model', to: 'openai:gpt-4.1-mini' })

    l.status('running').msg('assistant', 'def f(): ...').status('done')
    view_ = v(l.events)
    expect(kinds(view_.items)).toEqual(['user', 'prose', 'model', 'user', 'prose', 'nudge'])
  })

  it('shows on the pending turn before its message arrives', () => {
    const l = log().created('t', null).status('running').msg('user', 't').msg('assistant', 'a').status('done')
      .status('provisioning').add('session.model_changed', { from: 'a', to: 'b' })
    expect(kinds(v(l.events).items).slice(-3)).toEqual(['model', 'user', 'thinking'])
  })
})
