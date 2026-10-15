import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useContext, useEffect, useId, useRef, useState } from 'react'
import { api } from '@/api'
import { keys, useHealth } from '@/api/queries'
import { WORKERS_OFFLINE } from '@/composer/WorkersOffline'
import { sendProblem } from '@/composer/sendErrors'
import { cn } from '@/utils/cn'
import { Glyph, IC } from './icons'
import { checkResult, ciLabel, ciStale, duration, TONE, type Tone } from './ci'
import { PrActionsContext } from './prActions'
import type { Ci } from './reduce'

function ToneGlyph({ tone, size = 15 }: { tone: Tone; size?: number }) {
  if (tone === 'working') return <Glyph d={IC.spin} size={size} width={2.2} className="shrink-0 animate-spin-slow text-accent" />
  if (tone === 'ok') return <Glyph d={IC.checkCircle} size={size} width={1.8} className="shrink-0 text-ok" />
  if (tone === 'bad') return <Glyph d={IC.x} size={size} width={2.2} className="shrink-0 text-bad" />
  return <span aria-hidden="true" className="mx-[4px] size-[7px] shrink-0 rounded-full border-[1.5px] border-solid border-ter" />
}

/**
 * The CI row on the PR card: GitHub's CI for the commit Otto pushed last. A link to the run, the
 * checks behind a toggle, and, when it failed, "Fix CI": a follow-up turn in which Otto reads the
 * failing jobs' logs, fixes the problem and pushes to the same branch (so CI runs again). Fix CI
 * waits while Otto works, and is off while the workers are.
 */
export function CiRow({ sessionId, ci, live }: { sessionId: string; ci: Ci; live: boolean }) {
  const qc = useQueryClient()
  const actions = useContext(PrActionsContext)
  const health = useHealth()
  const [open, setOpen] = useState(false)
  const listId = useId()
  const fix = useMutation({
    mutationFn: () => actions.fixCi(sessionId),
    onError: (e) => {
      if (sendProblem(e).kind === 'offline') void qc.invalidateQueries({ queryKey: keys.health })
    },
  })
  // the fix's turn ran and ended without a new push (CI is the same): it can be asked for again
  const wasLive = useRef(false)
  useEffect(() => {
    if (live) wasLive.current = true
    else if (wasLive.current && fix.isSuccess) {
      wasLive.current = false
      fix.reset()
    }
  }, [live, fix])

  // CI that works for 2 hours without a change goes "unknown": the row looks again every minute
  const [now, setNow] = useState(() => Date.now())
  const working = ci.state === 'queued' || ci.state === 'running'
  useEffect(() => {
    if (!working) return
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [working])
  const stale = ciStale(ci, now)
  const check = useMutation({ mutationFn: () => api.checkCi(sessionId) })

  const label = ciLabel(ci, now)
  const problem = fix.error ? sendProblem(fix.error) : null
  const offline = health.data?.workers === 'offline' || problem?.kind === 'offline'
  const fixing = fix.isPending || fix.isSuccess
  const problemText =
    problem === null || problem.kind === 'offline'
      ? null
      : problem.kind === 'limit'
        ? "You've used today's limit. It resets at midnight UTC."
        : problem.message

  return (
    <div role="group" aria-label="CI" className="mt-4 border-0 border-t border-solid border-hair pt-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className={cn('inline-flex min-w-0 items-center gap-1.5 text-[13.5px] font-medium', TONE[label.tone])}>
          <ToneGlyph tone={label.tone} />
          <span className="truncate">{label.text}</span>
        </span>
        <div className="flex-1" />
        {ci.url && (
          <a href={ci.url} target="_blank" rel="noopener noreferrer" className="text-[13.5px]">
            View run
          </a>
        )}
        {ci.checks.length > 0 && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 border-0 bg-transparent p-0 text-[13.5px] text-muted hover:text-text"
          >
            {open ? 'Hide checks' : 'Show checks'}
            <Glyph d={IC.chevDown} size={13} width={2} className={cn('transition-transform', open && 'rotate-180')} />
          </button>
        )}
      </div>
      {open && (
        <ul id={listId} aria-label="Checks" className="m-0 mt-2.5 list-none space-y-1.5 p-0">
          {ci.checks.map((c) => {
            const r = checkResult(c)
            const took = c.status === 'completed' ? duration(c.duration) : null
            return (
              <li key={c.name} className="flex items-center gap-2 text-[13px]">
                <ToneGlyph tone={r.tone} size={13} />
                <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{c.name}</span>
                <span className={TONE[r.tone]}>{r.text}</span>
                {took && <span className="text-muted">{took}</span>}
                {c.url && (
                  <a href={c.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${c.name}`} className="inline-flex text-muted hover:text-text">
                    <Glyph d={IC.ext} size={13} width={1.8} />
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {stale && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
          <span>No news from GitHub for 2 hours.</span>
          <button
            type="button"
            disabled={check.isPending}
            onClick={() => check.mutate()}
            className="border-0 bg-transparent p-0 text-[13px] text-accent hover:text-accent-h disabled:text-muted"
          >
            {check.isPending ? 'Checking…' : 'Check again'}
          </button>
          {check.data?.ci === 'unknown' && !check.isPending && <span role="status">Still nothing new.</span>}
          {check.isError && (
            <span role="alert" className="text-bad">
              That didn't work. Try again.
            </span>
          )}
        </div>
      )}
      {ci.state === 'failed' && (
        <div className="mt-3">
          <button
            type="button"
            disabled={live || offline || fixing}
            aria-busy={fix.isPending}
            onClick={() => fix.mutate()}
            className="inline-flex h-8 items-center gap-1.5 rounded-full border border-solid border-line bg-transparent px-3.5 text-[13.5px] text-text hover:bg-hover disabled:opacity-50"
          >
            {fix.isPending ? <Glyph d={IC.spin} size={13} width={2.2} className="animate-spin-slow" /> : <Glyph d={IC.retry} size={13} width={2} />}
            {fixing ? 'Fixing CI…' : 'Fix CI'}
          </button>
          {offline && <p className="mb-0 mt-2 text-[13px] text-muted">{WORKERS_OFFLINE}</p>}
          {problemText && (
            <p role="alert" className="mb-0 mt-2 text-[13px] text-bad">
              {problemText}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
