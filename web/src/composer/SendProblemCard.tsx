import { AlertTriangle, Cpu } from 'lucide-react'
import { Link } from 'react-router'
import { number } from '@/utils/format'
import type { SendProblem } from './sendErrors'

/** Why the message didn't go: the design's usage-limit card, or its calm error card. */
export function SendProblemCard({ problem }: { problem: SendProblem }) {
  if (problem.kind === 'limit') {
    const { used, limit } = problem.limit
    const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 100
    return (
      <div role="alert" className="rounded-[18px] bg-bg2 px-[22px] py-5 text-left animate-rise">
        <div className="text-base font-semibold">You've used today's limit.</div>
        <div className="mt-[3px] text-[15px] text-muted">It resets at midnight UTC.</div>
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-line">
          <div className="h-full bg-muted" style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-2 flex items-baseline gap-3 text-[13px] text-muted">
          <span className="flex-1">
            {number(used)} of {number(limit)} tokens
          </span>
          <Link to="/settings/usage" className="text-sm">
            View usage ›
          </Link>
        </div>
      </div>
    )
  }
  const title = problem.kind === 'busy' ? 'Otto is busy right now.' : problem.kind === 'model' ? 'Pick another model.' : "Otto couldn't start this chat."
  const Icon = problem.kind === 'model' ? Cpu : AlertTriangle
  return (
    <div role="alert" className="rounded-[18px] border border-solid border-line bg-card px-5 py-[18px] text-left animate-rise">
      <div className="flex items-start gap-3">
        <Icon size={18} strokeWidth={1.8} className="mt-0.5 shrink-0" style={{ color: problem.kind === 'busy' ? 'var(--warn)' : 'var(--bad)' }} />
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">{title}</div>
          <div className="mt-[3px] text-[15px] leading-normal text-muted text-pretty">{problem.message}</div>
        </div>
      </div>
    </div>
  )
}
