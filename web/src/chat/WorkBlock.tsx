import { useEffect, useState, type ReactNode } from 'react'
import { ownerOf, shortName } from '@/utils/mention'
import { Glyph, IC } from './icons'
import { Markdown } from './Markdown'
import type { Note, Step, WorkBlock as Block } from './reduce'

/** "1m 48s", "38s" */
export function human(ms: number): string {
  const t = Math.max(0, Math.round(ms / 1000))
  return t >= 60 ? `${Math.floor(t / 60)}m ${String(t % 60).padStart(2, '0')}s` : `${t}s`
}

/** "1:02" */
export function mmss(ms: number): string {
  const t = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
}

/** Now, every second while `on`. */
export function useNow(on: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [on])
  return now
}

const ICON: Record<Step['icon'], string> = {
  run: IC.run,
  search: IC.search,
  file: IC.file,
  edit: IC.edit,
  push: IC.push,
  pr: IC.pr,
  commit: IC.push,
  git: IC.run,
}

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-md bg-tag px-1.5 py-px font-mono text-[.86em]">{children}</code>
}

/**
 * The work block: a card in the thread with the turn's steps. Live, it spins and counts up;
 * finished, it collapses to "7 steps · 9 passed · 1m 48s" and opens again on a click.
 */
export function WorkBlock({
  block,
  repo,
  branch,
  selected,
  onOpenStep,
  onOpenWorkspace,
}: {
  block: Block
  repo: string
  branch: string | null
  /** the step the workspace panel shows */
  selected: string | null
  onOpenStep: (step: Step) => void
  onOpenWorkspace: () => void
}) {
  const live = block.status === 'live' || block.status === 'setup'
  const [expanded, setExpanded] = useState<boolean | null>(null)
  const open = expanded ?? block.status !== 'done'
  const now = useNow(live)
  const elapsed = (block.endedAt ? Date.parse(block.endedAt) : now) - Date.parse(block.startedAt)
  const n = block.stepCount
  const steps = `${n} ${n === 1 ? 'step' : 'steps'}`

  const head = {
    setup: { color: 'var(--warn)', icon: IC.spin, spin: true },
    live: { color: 'var(--warn)', icon: IC.spin, spin: true },
    done: { color: 'var(--ok)', icon: IC.checkCircle, spin: false },
    failed: { color: 'var(--bad)', icon: IC.alert, spin: false },
    stopped: { color: 'var(--idle)', icon: IC.x, spin: false },
    paused: { color: 'var(--idle)', icon: IC.x, spin: false },
  }[block.status]

  const title: ReactNode = live ? (
    <>
      Working in <span className="font-normal text-muted">{ownerOf(repo)}/</span>
      {shortName(repo)}
    </>
  ) : block.status === 'done' ? (
    <>
      {steps}
      {block.tests && (
        <>
          {' · '}
          <span style={{ color: block.tests.failed || block.tests.errors ? 'var(--bad)' : 'var(--ok)' }}>{block.tests.text}</span>
        </>
      )}
      {` · ${human(elapsed)}`}
    </>
  ) : block.status === 'failed' || block.status === 'paused' ? (
    `Stopped after ${steps}`
  ) : (
    `You stopped Otto after ${steps}`
  )

  const meta = live ? (branch ?? '') : [repo, branch].filter(Boolean).join(' · ')
  const time = live ? mmss(elapsed) : block.status === 'failed' ? human(elapsed) : ''

  return (
    <div className="overflow-hidden rounded-[18px] border border-solid border-line bg-card">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setExpanded(!open)}
        className="flex w-full items-center gap-3 border-0 bg-transparent px-4 py-3.5 text-left text-text"
      >
        <span className="flex w-5 shrink-0 justify-center" style={{ color: head.color }}>
          <Glyph d={head.icon} size={18} width={1.8} className={head.spin ? 'animate-[otto-spin_1.1s_linear_infinite]' : undefined} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium">{title}</span>
          <span className="mt-px block truncate font-mono text-xs text-muted">{meta}</span>
        </span>
        {time && <span className="shrink-0 font-mono text-[12.5px] text-muted">{time}</span>}
        <Glyph
          d={IC.chevDown}
          size={16}
          width={1.8}
          className="shrink-0 text-muted transition-transform duration-300"
          style={{ transform: `rotate(${open ? 180 : 0}deg)` }}
        />
      </button>
      <div className="grid transition-[grid-template-rows] duration-[350ms] ease-in-out" style={{ gridTemplateRows: open ? '1fr' : '0fr' }}>
        <div className="min-h-0 overflow-hidden">
          <div className="border-0 border-t border-solid border-hair py-1.5">
            {block.rows.map((row) =>
              'note' in row ? <NoteRow key={row.id} note={row} /> : <StepRow key={row.id} step={row} live={live} selected={selected === row.id} onOpen={onOpenStep} />,
            )}
            {block.status === 'setup' && (
              <div className="flex items-start gap-3 bg-live-bg px-4 py-2 animate-rise">
                <span className="flex w-5 shrink-0 justify-center pt-0.5 text-warn">
                  <Glyph d={IC.spin} className="animate-spin-slow" />
                </span>
                <span className="text-[14.5px] text-muted">Setting up workspace…</span>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 border-0 border-t border-solid border-hair px-4 py-[11px]">
        <a
          href="#workspace"
          onClick={(e) => {
            e.preventDefault()
            onOpenWorkspace()
          }}
          className="inline-flex items-center gap-1.5 text-sm"
        >
          <Glyph d={IC.panel} size={14} />
          Open workspace
        </a>
      </div>
    </div>
  )
}

function NoteRow({ note }: { note: Note }) {
  return (
    <div className="flex gap-3 px-4 py-1.5 animate-rise">
      <span className="w-5 shrink-0" />
      <div className="min-w-0 flex-1 text-muted">
        <Markdown text={note.note} className="text-[14px] leading-normal" />
      </div>
    </div>
  )
}

function StepRow({ step, live, selected, onOpen }: { step: Step; live: boolean; selected: boolean; onOpen: (s: Step) => void }) {
  const running = step.ok === null && live
  const halted = step.ok === false && step.res?.text === 'Stopped'
  const failedModel = step.modelFailed === true
  const color = running
    ? 'var(--warn)'
    : halted
      ? 'var(--idle)'
      : step.ok === false
        ? 'var(--bad)'
        : step.res?.tone === 'ok'
          ? 'var(--ok)'
          : step.res?.tone === 'bad'
            ? 'var(--bad)'
            : 'var(--muted)'
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(step)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen(step))}
      className="flex cursor-pointer items-start gap-3 px-4 py-2 transition-[background] duration-200 animate-rise hover:bg-hover"
      style={{ background: running ? 'var(--live-bg)' : failedModel ? 'var(--bad-bg)' : selected ? 'var(--sel)' : undefined }}
    >
      <span className="flex w-5 shrink-0 justify-center pt-0.5" style={{ color }}>
        <Glyph d={running ? IC.spin : halted || failedModel ? IC.x : ICON[step.icon]} className={running ? 'animate-spin-slow' : undefined} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2.5">
          <span className="min-w-0 text-[14.5px] [overflow-wrap:anywhere]">
            {running ? step.now : step.verb}
            {step.code && (
              <>
                {' '}
                <Code>{step.code}</Code>
              </>
            )}
            {running && <span className="text-muted">…</span>}
          </span>
          <span className="ml-auto whitespace-nowrap text-sm">
            {!running && step.add !== null && <span className="font-mono text-[13px] text-ok">+{step.add}</span>}
            {!running && step.del ? <span className="font-mono text-[13px] text-bad"> −{step.del}</span> : null}
            {!running && step.res && (
              <span style={{ color: `var(--${step.res.tone})`, fontWeight: step.res.strong ? 600 : 400 }}>{step.res.text}</span>
            )}
          </span>
        </span>
        {step.sub && !running && (
          <span className="mt-[3px] block font-mono text-xs leading-normal text-muted [overflow-wrap:anywhere]">{step.sub}</span>
        )}
      </span>
    </div>
  )
}
