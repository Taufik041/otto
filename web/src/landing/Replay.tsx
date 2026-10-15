import { ArrowUp, AtSign, ChevronDown, Square } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { Glyph, IC } from '@/chat/icons'
import { PrActionsContext, type PrActions } from '@/chat/prActions'
import { emptyState, reduce, view } from '@/chat/reduce'
import { Thread } from '@/chat/Thread'
import { Workspace } from '@/chat/Workspace'
import { Lockup, Mark } from '@/components/brand'
import { IssueChip } from '@/composer/IssueChip'
import { IssueMenu } from '@/composer/IssueMenu'
import { ComposerPopover } from '@/composer/Popover'
import { MODELS } from '@/fixtures/session.js'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { elapsedOn, finalFrame, frameAt, INNER_H, INNER_W, LOOP_MS, loopOf, pause, resume, stoppedClock, type Clock, type Cursor, type Draft, type Target } from './replay'
import { BRANCH, ISSUE, PR_TITLE, REPO, TASK } from './scene'

const TICK_MS = 200
// a pretend "Create pull request" and "Fix CI": the cards show "Creating pull request…" and
// "Fixing CI…" until the script's next events play; nothing is sent anywhere
const PRETEND: PrActions = {
  create: () => new Promise((r) => setTimeout(r, 600)),
  decline: async () => {},
  fixCi: () => new Promise((r) => setTimeout(r, 600)),
}
const noop = () => {}
const BUTTON: Record<Target, string> = { create: 'Create pull request', fix: 'Fix CI' }
const MODEL_LABEL = MODELS.models.find((m) => m.id === MODELS.default_model)?.label ?? 'Otto'

/** On screen (enough of it to see), per IntersectionObserver; always, where there's none. */
function useOnScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([e]) => setOn(e?.isIntersecting ?? true), { threshold: 0.05 })
    io.observe(el)
    return () => io.disconnect()
  }, [ref])
  return on
}

function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])
  return visible
}

/**
 * Milliseconds of replay played, every TICK_MS while `running`; paused, it keeps its place. `wall`:
 * the wall-clock time the replay would have started at had it never paused (the events' times, so
 * a step's timer reads true after a pause).
 */
function usePlayhead(running: boolean): { elapsed: number; wall: number } {
  const clock = useRef<Clock>(stoppedClock)
  const [head, setHead] = useState(() => ({ elapsed: 0, wall: Date.now() }))
  useEffect(() => {
    if (!running) return
    clock.current = resume(clock.current, performance.now())
    const banked = clock.current.banked
    setHead({ elapsed: banked, wall: Date.now() - banked })
    const timer = setInterval(() => setHead((h) => ({ ...h, elapsed: elapsedOn(clock.current, performance.now()) })), TICK_MS)
    return () => {
      clearInterval(timer)
      clock.current = pause(clock.current, performance.now())
    }
  }, [running])
  return head
}

/**
 * The hero's live replay: Otto fixing an issue (./replay.ts) through the app's reducer, drawn by
 * the app's own Thread, Workspace, issue picker and PR cards, in a window frame. It plays while on
 * screen and the tab is visible, and picks up where it paused. Reduced motion: the final state,
 * still. `width`: the window's width in px (phones: wider than the screen, cropped by the page).
 */
export function Replay({ width }: { width: number }) {
  const root = useRef<HTMLDivElement>(null)
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)')
  const onScreen = useOnScreen(root)
  const visible = usePageVisible()
  const { elapsed, wall } = usePlayhead(!reduced && onScreen && visible)
  const loop = reduced ? 0 : loopOf(elapsed)
  const loopStart = wall + loop * LOOP_MS
  const frame = reduced ? finalFrame(wall) : frameAt(elapsed, loopStart)
  const count = frame.events.length
  // the view changes only when a beat passes (a new event), not on every tick
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  const v = useMemo(() => view(reduce(emptyState(), frame.events)), [count, loop, wall])

  const scale = (width - 12) / INNER_W
  return (
    <div
      ref={root}
      role="img"
      aria-label={`A replay of Otto at work: you pick issue #${ISSUE.number} in ${REPO}, Otto fixes it and opens "${PR_TITLE}", which closes the issue; a CI check fails, Otto fixes it on your click, and CI passes.`}
      data-replay
      className="relative rounded-2xl bg-bg2 p-1.5 shadow-[0_0_0_1px_var(--hair),0_9px_14px_-3px_rgba(0,0,0,.06)]"
      style={{ width }}
    >
      <div className="flex h-[30px] items-center gap-[7px] px-2.5" aria-hidden="true">
        <span className="size-[11px] rounded-full bg-[#FF5F57]" />
        <span className="size-[11px] rounded-full bg-[#FEBC2E]" />
        <span className="size-[11px] rounded-full bg-[#28C840]" />
        <Glyph d="M14.5 6l-6 6 6 6" size={14} width={2} className="ml-2.5 text-ter" />
        <Glyph d="M9.5 6l6 6-6 6" size={14} width={2} className="text-ter" />
        <div className="flex-1 text-center text-xs text-muted">ottoci.taufi.dev</div>
        <span className="w-[70px]" />
      </div>
      <div className="relative w-full overflow-hidden rounded-[11px] bg-bg shadow-[0_0_0_1px_var(--hair)]" style={{ height: Math.round(INNER_H * scale) }}>
        {/* the app at its own size, scaled down; inert: an illustration, not a second app */}
        <div
          inert
          className="absolute left-0 top-0 flex origin-top-left text-[15px]"
          style={{ width: INNER_W, height: INNER_H, transform: `scale(${scale})` }}
        >
          <PrActionsContext.Provider value={PRETEND}>
            <Inner
              key={loop}
              v={v}
              draft={frame.draft}
              tab={frame.tab}
              cursor={frame.cursor}
              target={frame.target}
              click={frame.click}
              fade={frame.fade}
              scale={scale}
            />
          </PrActionsContext.Provider>
        </div>
      </div>
    </div>
  )
}

const OTHER_CHATS = [
  { title: 'Show discount codes on the receipt', done: false },
  { title: 'Add line_count() to Order', done: true },
]

function Inner({
  v,
  draft,
  tab,
  cursor,
  target,
  click,
  fade,
  scale,
}: {
  v: ReturnType<typeof view>
  draft: Draft
  tab: 'terminal' | 'changes'
  cursor: Cursor
  target: Target | null
  click: Target | null
  fade: boolean
  scale: number
}) {
  const root = useRef<HTMLDivElement>(null)
  const thread = useRef<HTMLDivElement>(null)
  const [point, setPoint] = useState<{ x: number; y: number } | null>(null)
  const clicked = useRef(new Set<Target>())

  // keep the newest in view: the thread's end, and the workspace's latest command or file
  useLayoutEffect(() => {
    const scrollers = [thread.current, root.current?.querySelector('section[aria-label="Workspace"] .overflow-auto')]
    for (const el of scrollers) if (el) el.scrollTop = el.scrollHeight
  })

  // the target's button, in the unscaled coordinates the cursor moves in
  const button = (t: Target) =>
    [...(root.current?.querySelectorAll('button') ?? [])].find((b) => b.textContent?.trim() === BUTTON[t]) ?? null
  useLayoutEffect(() => {
    if (cursor !== 'button' || !target) return
    const b = button(target)
    const r = root.current?.getBoundingClientRect()
    if (!b || !r) return
    const box = b.getBoundingClientRect()
    setPoint({ x: (box.left - r.left) / scale + (box.width / scale) * 0.62, y: (box.top - r.top) / scale + (box.height / scale) * 0.55 })
  }, [cursor, target, scale])

  // press the real button, once a loop: the card shows its pending state until the script moves on
  useEffect(() => {

    if (!click || clicked.current.has(click)) return
    clicked.current.add(click)
    button(click)?.click()
  }, [click])

  const working = v.live
  const titled = v.items.some((i) => i.kind === 'proposal' || i.kind === 'pr')
  const chats = draft.sent ? [{ title: titled ? PR_TITLE : TASK, current: true, done: false }, ...OTHER_CHATS.map((c) => ({ ...c, current: false }))] : OTHER_CHATS.map((c) => ({ ...c, current: false }))
  return (
    <div ref={root} className="relative flex h-full w-full bg-bg text-text">
      <aside className="flex w-[210px] shrink-0 flex-col gap-0.5 border-0 border-r border-solid border-hair bg-bg2 px-2.5 py-3.5">
        <div className="px-1.5 pb-3.5">
          <Lockup height={18} />
        </div>
        <div
          className="flex h-[30px] items-center gap-2 rounded-lg border border-solid border-hair px-2 text-[12.5px]"
          style={{ background: draft.sent ? 'var(--card)' : 'var(--sel)' }}
        >
          <Glyph d={IC.edit} size={13} />
          New chat
        </div>
        <div className="px-2 pb-1 pt-3.5 text-[11px] font-medium text-muted">Today</div>
        {chats.map((s) => {
          const dot = s.current ? (working ? 'var(--accent)' : 'transparent') : s.done ? 'var(--ok)' : 'transparent'
          return (
            <div key={s.title} className="flex items-center gap-2 rounded-lg px-2 py-[7px] animate-fade" style={{ background: s.current ? 'var(--sel)' : undefined }}>
              <span className="min-w-0 flex-1 truncate text-[12.5px]">{s.title}</span>
              <span className={working && s.current ? 'size-1.5 rounded-full animate-pulse-dot' : 'size-1.5 rounded-full'} style={{ background: dot }} />
            </div>
          )
        })}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col transition-opacity duration-[900ms]" style={{ opacity: fade ? 0 : 1 }}>
        <div className="flex h-12 shrink-0 items-center gap-2 border-0 border-b border-solid border-hair px-[18px]">
          {draft.sent && (
            <>
              <span className="truncate text-[13.5px] tracking-[-0.03em]">{titled ? PR_TITLE : TASK}</span>
              <span className="shrink-0 rounded-md bg-tag px-[7px] py-0.5 font-mono text-[11px]">{REPO}</span>
              <span className="shrink-0 text-xs text-muted">{MODEL_LABEL}</span>
            </>
          )}
        </div>
        {draft.sent ? (
          <div ref={thread} className="min-h-0 flex-1 overflow-hidden px-6 pt-5">
            <div className="mx-auto max-w-[600px]">
              <Thread
                sessionId="replay"
                model={v.model}
                items={v.items}
                live={v.live}
                repo={REPO}
                branch={BRANCH}
                selectedStep={null}
                onOpenStep={noop}
                onOpenWorkspace={noop}
                onSeeChanges={noop}
                onMention={noop}
              />
            </div>
          </div>
        ) : (
          // the new-chat page's greeting
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-8 pb-6 text-center">
            <Mark size={40} className="mb-4" />
            <div className="text-[32px] leading-[1.1] tracking-[-0.03em]">What should we build today?</div>
          </div>
        )}
        <div className="shrink-0 px-6 pb-3">
          <ReplayComposer draft={draft} working={working} />
        </div>
      </div>

      {draft.sent && (
        <div className="flex w-[400px] shrink-0 flex-col transition-opacity duration-[900ms] animate-fade [&>section]:!animate-none" style={{ opacity: fade ? 0 : 1 }}>
          <Workspace
            repo={REPO}
            branch={BRANCH}
            files={v.files}
            terminal={v.terminal}
            state={{ tab, path: null, entry: null }}
            onState={noop}
            onClose={noop}
            mobile={false}
          />
        </div>
      )}

      {cursor !== 'hidden' && (
        <svg
          aria-hidden="true"
          width="26"
          height="26"
          viewBox="0 0 24 24"
          data-cursor
          className="pointer-events-none absolute z-50 drop-shadow-[0_2px_3px_rgba(0,0,0,.25)]"
          style={{
            left: cursor === 'button' && point ? point.x : 760,
            top: cursor === 'button' && point ? point.y : 600,
            transform: click ? 'scale(.85)' : 'none',
            transition: 'left 1.3s cubic-bezier(.4,0,.2,1), top 1.3s cubic-bezier(.4,0,.2,1), transform .15s ease',
          }}
        >
          <path d="M5 3l14 8.2-6.1 1.4-3.3 5.9z" fill="#15171C" stroke="#FFFFFF" strokeWidth="1.4" strokeLinejoin="round" />
        </svg>
      )}
    </div>
  )
}

/**
 * The composer as the script types in it: the app's issue picker (its popover and list) and issue
 * chip, in the composer's own box. A stand-in for the textarea: the replay never takes input.
 */
function ReplayComposer({ draft, working }: { draft: Draft; working: boolean }) {
  const canSend = !draft.sent && (draft.text.trim().length > 0 || draft.issue !== null)
  const placeholder = working
    ? 'Otto is working…'
    : draft.sent
      ? 'Reply to Otto. Type # to pick an issue.'
      : 'Message Otto. Type @ to mention a repo.'
  return (
    <div className="relative mx-auto w-full max-w-[620px]">
      {draft.picker && (
        <ComposerPopover mobile={false} below={false} width={460} onClose={noop} label="Pick an issue">
          <IssueMenu
            repo={REPO}
            issues={draft.picker.issues}
            query={draft.picker.query}
            active={draft.picker.active}
            mobile={false}
            onPick={noop}
            onHover={noop}
          />
        </ComposerPopover>
      )}
      <div
        className="rounded-3xl border border-solid bg-card shadow-card transition-[border-color] duration-200"
        style={{ padding: '14px 12px 10px 18px', borderColor: draft.picker ? 'var(--accent)' : 'var(--line)' }}
      >
        <div className="flex flex-wrap items-start gap-1.5">
          {draft.issue && <IssueChip issue={draft.issue} onRemove={noop} />}
          <div data-draft className="min-h-[26px] min-w-[120px] flex-[1_1_180px] whitespace-pre-wrap py-0.5 text-base leading-[1.55]">
            {draft.text || draft.issue ? (
              <>
                {draft.text}
                <span aria-hidden="true" className="ml-px inline-block h-[1.15em] w-[1.5px] translate-y-[3px] bg-text animate-pulse-dot" />
              </>
            ) : (
              <span className="text-muted">{placeholder}</span>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <span className="-ml-2 flex h-8 items-center gap-1.5 px-2.5 text-[13.5px] font-medium text-muted">
            {MODEL_LABEL}
            <ChevronDown size={13} strokeWidth={2} />
          </span>
          <span className="flex size-8 items-center justify-center text-muted">
            <AtSign size={17} strokeWidth={1.7} />
          </span>
          <div className="flex-1" />
          <span
            className="flex size-[34px] items-center justify-center rounded-full"
            style={{ background: canSend || working ? 'var(--inv)' : 'var(--sel)', color: canSend || working ? 'var(--inv-text)' : 'var(--muted)' }}
          >
            {working ? <Square size={13} fill="currentColor" strokeWidth={0} /> : <ArrowUp size={16} strokeWidth={2.2} />}
          </span>
        </div>
      </div>
    </div>
  )
}
