import { emptyState, reduce, view } from '@/chat/reduce'
import { CLICK_AT, CURSOR_AT, FADE_AT, finalFrame, frameAt, LOOP_MS, OPENED_AT, PROPOSED_AT } from './replay'

const START = Date.parse('2026-10-08T12:00:00Z')
const at = (ms: number) => frameAt(ms, START)
const v = (ms: number) => view(reduce(emptyState(), at(ms).events))
const kinds = (ms: number) => v(ms).items.map((i) => i.kind)

describe('the hero replay: a real session, played on a clock', () => {
  it('loops in about 35 seconds', () => {
    expect(LOOP_MS).toBeGreaterThanOrEqual(30_000)
    expect(LOOP_MS).toBeLessThanOrEqual(40_000)
  })

  it('starts with the message, and only grows: each frame\'s events extend the last', () => {
    expect(kinds(0)).toEqual(['user', 'work']) // the message, and Otto setting up its workspace
    let prev = at(0).events
    for (let t = 250; t < LOOP_MS; t += 250) {
      const events = at(t).events
      expect(events.slice(0, prev.length)).toEqual(prev)
      expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1))
      prev = events
    }
  })

  it('event times are real: the loop\'s start plus their beat', () => {
    const [first] = at(0).events
    expect(Date.parse(first!.ts)).toBe(START)
    expect(Date.parse(at(LOOP_MS - 1).events.at(-1)!.ts)).toBeLessThan(START + LOOP_MS)
  })

  it('steps, then 2 failed in the Terminal', () => {
    const w = v(5_000)
    expect(w.live).toBe(true)
    expect(w.terminal[0]).toMatchObject({ cmd: 'python -m pytest -q', exit: 1 })
    expect(w.terminal[0]!.tests).toMatchObject({ failed: 2, passed: 7 })
    expect(at(5_000).tab).toBe('terminal')
  })

  it('then the one-line diff in Changes', () => {
    const w = v(11_500)
    expect(w.files[0]).toMatchObject({ path: 'src/inventory/pricing.py', kind: 'Edited', add: 1, del: 1 })
    expect(at(11_500).tab).toBe('changes')
  })

  it('then 9 passed, back in the Terminal', () => {
    const w = v(14_500)
    expect(w.terminal.at(-1)!.tests).toMatchObject({ passed: 9, failed: 0 })
    expect(at(14_500).tab).toBe('terminal')
  })

  it('then the reply and "Ready for review", with Otto done', () => {
    const w = v(PROPOSED_AT + 100)
    expect(w.live).toBe(false)
    expect(w.items.map((i) => i.kind)).toEqual(['user', 'prose', 'work', 'prose', 'proposal'])
  })

  it('a cursor comes, clicks Create, and the PR opens', () => {
    expect(at(CURSOR_AT - 1).cursor).toBe('hidden')
    expect(at(CURSOR_AT + 50).cursor).toBe('start')
    expect(at(CURSOR_AT + 400).cursor).toBe('button')
    expect(at(CLICK_AT - 1).click).toBe(false)
    expect(at(CLICK_AT).click).toBe(true)
    expect(kinds(OPENED_AT - 1).at(-1)).toBe('proposal')
    expect(kinds(OPENED_AT).at(-1)).toBe('pr')
    expect(at(OPENED_AT + 1_500).cursor).toBe('hidden')
  })

  it('fades out at the end, then starts over', () => {
    expect(at(FADE_AT - 1).fade).toBe(false)
    expect(at(FADE_AT).fade).toBe(true)
    expect(at(LOOP_MS + 10).events).toEqual(at(10).events)
    expect(at(3 * LOOP_MS + 12_000).tab).toBe(at(12_000).tab)
  })

  it('reduced motion: the final state, still (no cursor, no fade)', () => {
    const f = finalFrame(START)
    const w = view(reduce(emptyState(), f.events))
    expect(w.items.at(-1)).toMatchObject({ kind: 'pr', pr: { number: 9, title: 'Fix bulk discount threshold' } })
    expect(w.live).toBe(false)
    expect(f).toMatchObject({ cursor: 'hidden', click: false, fade: false })
  })
})
