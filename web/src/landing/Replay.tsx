import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Glyph, IC } from '@/chat/icons'
import { PrActionsContext, type PrActions } from '@/chat/prActions'
import { emptyState, reduce, view } from '@/chat/reduce'
import { Thread } from '@/chat/Thread'
import { Workspace } from '@/chat/Workspace'
import { Lockup } from '@/components/brand'
import { BRANCH, PR_TITLE, REPO } from '@/fixtures/session.js'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { finalFrame, frameAt, INNER_H, INNER_W, LOOP_MS, loopOf, seedCatalog } from './replay'

const TICK_MS = 200
// a pretend "Create pull request": the card shows "Creating pull request…" until pr.opened plays
const PRETEND: PrActions = { create: () => new Promise((r) => setTimeout(r, 600)), decline: async () => {} }
const noop = () => {}

/** Milliseconds since the replay started, every TICK_MS (frozen at 0 with reduced motion). */
function useElapsed(running: boolean): number {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!running) return
    const start = performance.now()
    const timer = setInterval(() => setElapsed(performance.now() - start), TICK_MS)
    return () => clearInterval(timer)
  }, [running])
  return elapsed
}

/**
 * The hero's live replay: a real session (./replay.ts) through the app's reducer, drawn by the
 * app's own Thread and Workspace, in a window frame. Reduced motion: the final state, still.
 * `width`: the window's width in px (phones: wider than the screen, cropped by the page).
 */
export function Replay({ width }: { width: number }) {
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)')
  const elapsed = useElapsed(!reduced)
  const [wallStart] = useState(() => Date.now())
  const loop = reduced ? 0 : loopOf(elapsed)
  const loopStart = wallStart + loop * LOOP_MS
  const frame = reduced ? finalFrame(wallStart) : frameAt(elapsed, loopStart)
  const count = frame.events.length
  // the view changes only when a beat passes (a new event), not on every tick
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  const v = useMemo(() => view(reduce(emptyState(), frame.events)), [count, loop])

  // keep the fixture catalog fresh, so a remount each loop never refetches it
  const qc = useQueryClient()
  useEffect(() => seedCatalog(qc), [qc, loop])

  const scale = (width - 12) / INNER_W
  return (
    <div
      role="img"
      aria-label={`A replay of Otto at work: it finds why two tests fail, fixes the source, runs the tests, and opens "${PR_TITLE}" once you approve.`}
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
            <Inner key={loop} v={v} tab={frame.tab} cursor={frame.cursor} click={frame.click} fade={frame.fade} scale={scale} />
          </PrActionsContext.Provider>
        </div>
      </div>
    </div>
  )
}

const SIDEBAR = [
  { title: 'Fix bulk discount threshold', current: true },
  { title: 'Portfolio contact form', current: false },
  { title: 'Add line_count() to Order', current: false, done: true },
]

function Inner({
  v,
  tab,
  cursor,
  click,
  fade,
  scale,
}: {
  v: ReturnType<typeof view>
  tab: 'terminal' | 'changes'
  cursor: 'hidden' | 'start' | 'button'
  click: boolean
  fade: boolean
  scale: number
}) {
  const root = useRef<HTMLDivElement>(null)
  const thread = useRef<HTMLDivElement>(null)
  const [target, setTarget] = useState<{ x: number; y: number } | null>(null)
  const clicked = useRef(false)

  // keep the newest in view: the thread's end, and the workspace's latest command or file
  useLayoutEffect(() => {
    const scrollers = [thread.current, root.current?.querySelector('section[aria-label="Workspace"] .overflow-auto')]
    for (const el of scrollers) if (el) el.scrollTop = el.scrollHeight
  })

  // the Create button, in the unscaled coordinates the cursor moves in
  const createButton = () =>
    [...(root.current?.querySelectorAll('button') ?? [])].find((b) => b.textContent?.includes('Create pull request')) ?? null
  useLayoutEffect(() => {
    if (cursor !== 'button') return
    const b = createButton()
    const r = root.current?.getBoundingClientRect()
    if (!b || !r) return
    const box = b.getBoundingClientRect()
    setTarget({ x: (box.left - r.left) / scale + (box.width / scale) * 0.62, y: (box.top - r.top) / scale + (box.height / scale) * 0.55 })
  }, [cursor, scale])

  // press the real button, once: the card shows "Creating pull request…", then pr.opened plays
  useEffect(() => {
    if (!click || clicked.current) return
    clicked.current = true
    createButton()?.click()
  }, [click])

  const working = v.live
  return (
    <div ref={root} className="relative flex h-full w-full bg-bg text-text">
      <aside className="flex w-[210px] shrink-0 flex-col gap-0.5 border-0 border-r border-solid border-hair bg-bg2 px-2.5 py-3.5">
        <div className="px-1.5 pb-3.5">
          <Lockup height={18} />
        </div>
        <div className="flex h-[30px] items-center gap-2 rounded-lg border border-solid border-hair bg-card px-2 text-[12.5px]">
          <Glyph d={IC.edit} size={13} />
          New chat
        </div>
        <div className="px-2 pb-1 pt-3.5 text-[11px] font-medium text-muted">Today</div>
        {SIDEBAR.map((s) => {
          const dot = s.current ? (working ? 'var(--accent)' : 'transparent') : s.done ? 'var(--ok)' : 'transparent'
          return (
            <div key={s.title} className="flex items-center gap-2 rounded-lg px-2 py-[7px]" style={{ background: s.current ? 'var(--sel)' : undefined }}>
              <span className="min-w-0 flex-1 truncate text-[12.5px]">{s.title}</span>
              <span className={working && s.current ? 'size-1.5 rounded-full animate-pulse-dot' : 'size-1.5 rounded-full'} style={{ background: dot }} />
            </div>
          )
        })}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col transition-opacity duration-[900ms]" style={{ opacity: fade ? 0 : 1 }}>
        <div className="flex h-12 shrink-0 items-center gap-2 border-0 border-b border-solid border-hair px-[18px]">
          <span className="text-[13.5px] tracking-[-0.03em]">{PR_TITLE}</span>
          <span className="rounded-md bg-tag px-[7px] py-0.5 font-mono text-[11px]">{REPO}</span>
          <span className="text-xs text-muted">Otto</span>
        </div>
        <div ref={thread} className="min-h-0 flex-1 overflow-hidden px-6 pt-5">
          <div className="mx-auto max-w-[600px]">
            <Thread
              sessionId="replay"
              model={v.model}
              items={v.items}
              live={v.live}
              repo={REPO}
              branch={BRANCH}
              sent={null}
              selectedStep={null}
              onOpenStep={noop}
              onOpenWorkspace={noop}
              onSeeChanges={noop}
              onMention={noop}
            />
          </div>
        </div>
        <div className="shrink-0 px-6 pb-2.5">
          <div className="mx-auto max-w-[620px] rounded-[20px] border border-solid border-line bg-card px-3.5 pb-2 pt-2.5 shadow-card">
            <div className="text-sm text-muted">{working ? 'Otto is working…' : 'Reply to Otto…'}</div>
            <div className="mt-2 flex items-center">
              <span className="text-xs font-medium text-muted">Otto ▾</span>
              <span className="flex-1" />
              <span className="size-[26px] rounded-full" style={{ background: working ? 'var(--inv)' : 'var(--sel)' }} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex w-[400px] shrink-0 flex-col transition-opacity duration-[900ms] [&>section]:!animate-none" style={{ opacity: fade ? 0 : 1 }}>
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

      {cursor !== 'hidden' && (
        <svg
          aria-hidden="true"
          width="26"
          height="26"
          viewBox="0 0 24 24"
          data-cursor
          className="pointer-events-none absolute z-10 drop-shadow-[0_2px_3px_rgba(0,0,0,.25)]"
          style={{
            left: cursor === 'button' && target ? target.x : 640,
            top: cursor === 'button' && target ? target.y : 600,
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
