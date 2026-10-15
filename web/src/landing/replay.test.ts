import { emptyState, reduce, view, type Item } from '@/chat/reduce'
import { draftAt, elapsedOn, finalFrame, frameAt, LOOP_MS, pause, resume, stoppedClock, T } from './replay'
import { REPO } from './scene'

const START = Date.parse('2026-10-08T12:00:00Z')
const at = (ms: number) => frameAt(ms, START)
const v = (ms: number) => view(reduce(emptyState(), at(ms).events))
const kinds = (ms: number) => v(ms).items.map((i) => i.kind)
const last = <K extends Item['kind']>(ms: number, kind: K) =>
  v(ms).items.findLast((i) => i.kind === kind) as Extract<Item, { kind: K }> | undefined

describe('the hero replay: an issue fixed, played on a clock', () => {
  it('loops in 40 to 50 seconds, and every beat lands inside the loop, before the fade', () => {
    expect(LOOP_MS).toBeGreaterThanOrEqual(40_000)
    expect(LOOP_MS).toBeLessThanOrEqual(50_000)
    expect(at(T.fade - 1).events).toEqual(finalFrame(START).events)
  })

  it('every step stays on screen long enough to read: beats 0.7s apart at least, the key ones longer', () => {
    const moments = Object.values(T).sort((a, b) => a - b)
    for (const [i, t] of moments.slice(1).entries()) expect(t - moments[i]!).toBeGreaterThanOrEqual(700)
    expect(T.move - T.typeQuery).toBeGreaterThanOrEqual(1_200) // the narrowed list
    expect(T.ciFailed - T.ciRunning).toBeGreaterThanOrEqual(1_200)
    expect(T.fade - T.ciPassed).toBeGreaterThanOrEqual(3_000) // the payoff holds
  })

  it('only grows: each frame\'s events extend the last, numbered in order', () => {
    let prev = at(0).events
    for (let t = 250; t < LOOP_MS; t += 250) {
      const events = at(t).events
      expect(events.slice(0, prev.length)).toEqual(prev)
      expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1))
      prev = events
    }
  })

  it('event times are real: the loop\'s start plus their beat', () => {
    const [first] = at(T.send).events
    expect(Date.parse(first!.ts)).toBe(START + T.send)
    expect(Date.parse(at(LOOP_MS - 1).events.at(-1)!.ts)).toBeLessThan(START + LOOP_MS)
  })

  describe('a. the composer', () => {
    it('starts empty, then "@acme/shop " is typed, a key at a time', () => {
      expect(draftAt(0)).toMatchObject({ text: '', picker: null, issue: null, sent: false })
      expect(draftAt(T.typeRepo).text).toBe('@')
      expect(draftAt(T.typeRepo + 400).text.length).toBeGreaterThan(1)
      expect(draftAt(T.hash - 1).text).toBe(`@${REPO} `)
      expect(at(T.hash - 1).events).toEqual([]) // nothing has happened yet
    })

    it('# opens the issue picker with the 3 open issues', () => {
      const d = draftAt(T.hash)
      expect(d.text).toBe(`@${REPO} #`)
      expect(d.picker?.issues.map((i) => i.number)).toEqual([14, 12, 11])
      expect(d.picker?.active).toBe(0)
    })

    it('"disc" narrows it, and the highlight moves to #12', () => {
      const d = draftAt(T.move - 1)
      expect(d.text).toBe(`@${REPO} #disc`)
      expect(d.picker?.issues.map((i) => i.number)).toEqual([14, 12])
      expect(d.picker?.active).toBe(0)
      expect(draftAt(T.move).picker?.active).toBe(1)
    })

    it('picked: #12\'s chip, the #query gone, the picker closed', () => {
      const d = draftAt(T.pick)
      expect(d.issue).toMatchObject({ number: 12, title: 'Bulk discount not applied at exactly 10 units' })
      expect(d).toMatchObject({ text: `@${REPO} `, picker: null, sent: false })
    })

    it('sent: the composer empties and the session starts', () => {
      expect(draftAt(T.send)).toMatchObject({ text: '', issue: null, sent: true })
      expect(at(T.send).events[0]!.type).toBe('session.created')
    })
  })

  it('b. the message shows the issue\'s card: number, title, Open, one label', () => {
    expect(kinds(T.send)).toEqual(['user', 'work'])
    expect(v(T.send).items[0]).toMatchObject({
      kind: 'user',
      text: 'Fix #12',
      repo: REPO,
      issue: { number: 12, title: 'Bulk discount not applied at exactly 10 units', state: 'open', labels: ['bug'] },
    })
  })

  it('c. Otto works: a short message, a few steps, the diff in Changes, then 9 passed', () => {
    const w = v(T.diff + 100)
    expect(w.live).toBe(true)
    expect(w.items[1]).toMatchObject({ kind: 'prose' })
    expect(w.files[0]).toMatchObject({ path: 'src/shop/pricing.py', kind: 'Edited', add: 1, del: 1 })
    expect(at(T.diff + 100).tab).toBe('changes')

    const passed = v(T.passed)
    expect(passed.terminal.at(-1)).toMatchObject({ cmd: 'python -m pytest -q', exit: 0 })
    expect(passed.terminal.at(-1)!.tests).toMatchObject({ passed: 9, failed: 0 })
    expect(at(T.passed).tab).toBe('terminal')
    const block = last(T.passed, 'work')!.block
    expect(block.stepCount).toBeLessThanOrEqual(4)
  })

  it('d. the proposal says "Closes #12"; the cursor clicks Create; the PR card is Open', () => {
    const p = last(T.proposed, 'proposal')
    expect(v(T.proposed).live).toBe(false)
    expect(p?.proposal).toMatchObject({ issues: [{ number: 12 }], tests: { passed: 9, failed: 0 } })

    expect(at(T.cursor - 1).cursor).toBe('hidden')
    expect(at(T.cursor + 50)).toMatchObject({ cursor: 'start', target: 'create' })
    expect(at(T.cursor + 400)).toMatchObject({ cursor: 'button', target: 'create', click: null })
    expect(at(T.click).click).toBe('create')
    expect(kinds(T.opened - 1).at(-1)).toBe('proposal')

    const pr = last(T.opened, 'pr')
    expect(pr?.pr).toMatchObject({ number: 15, updated: false, issues: [{ number: 12 }] })
    expect(at(T.opened).click).toBe(null)
  })

  it('e. CI: waiting, running, one check fails; Fix CI is clicked; Otto pushes; CI passes', () => {
    expect(last(T.ciWaiting, 'pr')?.ci).toMatchObject({ state: 'queued', checks: [] })
    expect(last(T.ciRunning, 'pr')?.ci).toMatchObject({ state: 'running' })
    const failed = last(T.ciFailed, 'pr')!.ci!
    expect(failed.state).toBe('failed')
    expect(failed.checks.filter((c) => c.conclusion === 'failure').map((c) => c.name)).toEqual(['tests'])
    expect(last(T.ciFailed, 'ci')).toMatchObject({ text: 'CI failed · tests' })

    expect(at(T.fixCursor + 400)).toMatchObject({ cursor: 'button', target: 'fix' })
    expect(at(T.fixClick).click).toBe('fix')

    const fixing = v(T.fixing)
    expect(fixing.live).toBe(true)
    expect(fixing.items.findLast((i) => i.kind === 'user')).toMatchObject({ text: 'Fix CI: tests' })
    expect(at(T.fixDiff + 100).tab).toBe('changes')
    const fixed = last(T.updated, 'work')!.block
    expect(fixed.rows.at(-1)).toMatchObject({ verb: 'Pushed to pull request', code: '#15' })

    const updated = last(T.updated, 'pr')!
    expect(updated.pr).toMatchObject({ updated: true, number: 15, issues: [{ number: 12 }] })
    expect(last(T.ciRerun, 'pr')?.ci).toMatchObject({ state: 'queued' })
    expect(last(T.ciRerunning, 'pr')?.ci).toMatchObject({ state: 'running' })
    expect(last(T.ciPassed, 'pr')?.ci).toMatchObject({ state: 'passed' })
    expect(last(T.ciPassed, 'ci')).toMatchObject({ text: 'CI passed · 2 checks' })
    expect(v(T.ciPassed).live).toBe(false)
  })

  it('fades out at the end, then starts over', () => {
    expect(at(T.fade - 1).fade).toBe(false)
    expect(at(T.fade).fade).toBe(true)
    expect(at(LOOP_MS + 10)).toEqual(at(10))
    expect(at(3 * LOOP_MS + T.fixDiff + 100).tab).toBe('changes')
  })

  it('reduced motion: the final frame, still: the PR with CI passed and Closes #12', () => {
    const f = finalFrame(START)
    const w = view(reduce(emptyState(), f.events))
    const pr = w.items.findLast((i) => i.kind === 'pr')
    expect(pr).toMatchObject({ pr: { number: 15, issues: [{ number: 12 }] }, ci: { state: 'passed' } })
    expect(w.live).toBe(false)
    expect(f).toMatchObject({ cursor: 'hidden', click: null, fade: false, draft: { sent: true } })
  })
})

describe('the replay\'s clock', () => {
  it('runs from 0 once started', () => {
    const c = resume(stoppedClock, 1_000)
    expect(elapsedOn(stoppedClock, 5_000)).toBe(0)
    expect(elapsedOn(c, 3_500)).toBe(2_500)
  })

  it('a pause keeps its place, however long; resuming carries on from there', () => {
    let c = resume(stoppedClock, 0)
    c = pause(c, 12_000)
    expect(elapsedOn(c, 90_000)).toBe(12_000) // off screen for a while: nothing moved
    c = resume(c, 90_000)
    expect(elapsedOn(c, 91_000)).toBe(13_000)
    expect(pause(pause(c, 92_000), 99_000)).toEqual(pause(c, 92_000)) // pausing twice is once
    expect(resume(c, 95_000)).toBe(c) // so is resuming
  })
})
