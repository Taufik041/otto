import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { keys, useModels, useUsage } from '@/api/queries'
import type { Usage } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { compact, number, shortDate, usd } from '@/utils/format'
import { Card, Loading, Problem } from './parts'

export function UsagePage() {
  const usage = useUsage()
  const models = useModels()
  if (usage.isPending) return <Loading />
  if (usage.isError) return <Problem error={usage.error} />
  const u = usage.data
  const label = (id: string) => models.data?.models.find((m) => m.id === id)?.label ?? id
  return (
    <>
      <Today today={u.today} />
      <Card className="p-[22px]">
        <div className="text-[17px] font-semibold">This month</div>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Stat value={number(u.month.sessions)} label="sessions" />
          <Stat value={compact(u.month.tokens)} label="tokens" />
          <Stat value={usd(u.month.est_cost_usd)} label="estimated cost" />
        </div>
        <Daily daily={u.daily} />
        {u.by_model.length > 0 && (
          <div className="mt-6 border-0 border-t border-solid border-hair">
            {u.by_model.map((m) => {
              const pct = u.month.tokens ? Math.round((m.tokens / u.month.tokens) * 100) : 0
              return (
                <div key={m.model} className="flex items-center gap-3 border-0 border-b border-solid border-hair py-3">
                  <span className="min-w-0 shrink-0 basis-[36%] truncate text-[14.5px]">{label(m.model)}</span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-sel" aria-hidden="true">
                    <span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="w-16 shrink-0 text-right font-mono text-[12.5px] text-muted">
                    {compact(m.tokens)}
                    <span className="sr-only"> tokens, {pct}% of this month</span>
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </Card>
      <Sandboxes list={u.active_sandboxes} />
    </>
  )
}

function Today({ today }: { today: Usage['today'] }) {
  const pct = today.limit > 0 ? Math.min(100, (today.tokens / today.limit) * 100) : 0
  return (
    <Card className="px-[22px] pb-5 pt-[22px]">
      <div className="flex items-baseline gap-2.5">
        <span className="flex-1 text-[17px] font-semibold">Today</span>
        <span className="text-[13px] text-muted">Resets at midnight UTC</span>
      </div>
      <div className="mt-3.5 text-[28px] font-semibold tracking-[-0.02em]">
        {number(today.tokens)} <span className="text-[17px] font-normal text-muted">of {number(today.limit)} tokens</span>
      </div>
      <div
        role="meter"
        aria-label="Tokens used today"
        aria-valuemin={0}
        aria-valuemax={today.limit}
        aria-valuenow={Math.min(today.tokens, today.limit)}
        aria-valuetext={`${number(today.tokens)} of ${number(today.limit)} tokens`}
        className="mt-3.5 h-2 overflow-hidden rounded-full bg-sel"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </Card>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold tracking-[-0.02em]">{value}</div>
      <div className="text-[13px] text-muted">{label}</div>
    </div>
  )
}

/** Tokens per day: one accent, the design's rounded bars; hover or focus a day for its total. */
function Daily({ daily }: { daily: Usage['daily'] }) {
  const mobile = useIsMobile()
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...daily.map((d) => d.tokens))
  const mid = daily[Math.floor((daily.length - 1) / 2)]
  const tip = (i: number) => {
    const d = daily[i]!
    return `${i === daily.length - 1 ? 'Today' : shortDate(d.date)} · ${number(d.tokens)} tokens`
  }
  return (
    <>
      <div className="mt-[26px] text-[13px] text-muted" id="daily-title">
        Tokens per day, last {daily.length} days
      </div>
      <div className="relative mt-3 flex h-[120px] items-end" style={{ gap: mobile ? 4 : 8 }} aria-hidden="true">
        {daily.map((d, i) => (
          <div
            key={d.date}
            className="flex h-full flex-1 basis-0 items-end"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <div
              className="w-full rounded-[4px_4px_2px_2px]"
              style={{
                height: `${(d.tokens / max) * 100}%`,
                minHeight: 3,
                background: d.tokens ? 'var(--accent)' : 'var(--line)',
                opacity: hover === null || hover === i ? 1 : 0.55,
              }}
            />
          </div>
        ))}
        {hover !== null && (
          <div
            className="pointer-events-none absolute -top-8 z-10 -translate-x-1/2 whitespace-nowrap rounded-lg border border-solid border-line bg-card px-2.5 py-1 text-xs text-text shadow-pop"
            style={{ left: `${((hover + 0.5) / daily.length) * 100}%` }}
          >
            {tip(hover)}
          </div>
        )}
      </div>
      <div className="mt-2 flex text-[11.5px] text-muted" aria-hidden="true">
        <span className="flex-1">{daily[0] && shortDate(daily[0].date)}</span>
        <span className="flex-1 text-center">{mid && shortDate(mid.date)}</span>
        <span>Today</span>
      </div>
      <table className="sr-only" aria-labelledby="daily-title">
        <thead>
          <tr>
            <th>Day</th>
            <th>Tokens</th>
          </tr>
        </thead>
        <tbody>
          {daily.map((d) => (
            <tr key={d.date}>
              <td>{d.date}</td>
              <td>{d.tokens}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function Sandboxes({ list }: { list: Usage['active_sandboxes'] }) {
  const qc = useQueryClient()
  const stop = useMutation({
    mutationFn: api.stopSandbox,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.usage })
      qc.invalidateQueries({ queryKey: keys.sessions })
    },
  })
  return (
    <Card className="p-[22px]">
      <div className="flex items-baseline gap-2.5">
        <span className="flex-1 text-[17px] font-semibold">Active sandboxes</span>
        <span className="text-[13px] text-muted">{list.length}</span>
      </div>
      {list.length === 0 ? (
        <p className="mb-0 mt-2 text-sm text-muted">No sandboxes are running.</p>
      ) : (
        <div className="mt-3">
          {list.map((s, i) => (
            <div
              key={s.session_id}
              className="flex items-center gap-3 py-3"
              style={{ borderTop: i ? '1px solid var(--hair)' : 'none' }}
            >
              <span className="size-1.5 shrink-0 rounded-full bg-ok" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <Link to={`/c/${s.session_id}`} className="block truncate text-[15px] text-text hover:text-text">
                  {s.title}
                </Link>
                <span className="block truncate font-mono text-xs text-muted">{s.repo}</span>
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={stop.isPending && stop.variables === s.session_id}
                onClick={() => stop.mutate(s.session_id)}
              >
                Stop
              </Button>
            </div>
          ))}
        </div>
      )}
      {stop.isError && <p role="alert" className="mb-0 mt-2 text-sm text-bad">{messageOf(stop.error)}</p>}
    </Card>
  )
}
