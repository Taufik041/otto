import type { ReactNode } from 'react'
import { GitHubIcon } from '@/components/brand'
import { Glyph, IC } from './icons'
import type { PrCard as Pr, TestSummary } from './reduce'

type Counts = { additions: number | null; deletions: number | null; files: number | null; tests: number | null }

/**
 * The pull-request card family: the blue line on the left, a head with a badge, the title, where
 * it goes, the counts, and the card's own buttons. The proposal and the opened PR share it.
 */
export function PrFrame({
  label,
  head,
  opened,
  badge,
  title,
  number,
  repo,
  branch,
  base,
  counts,
  children,
}: {
  /** the region's name for screen readers */
  label: string
  head: string
  /** on GitHub already: the green icon and badge */
  opened: boolean
  badge: string
  title: string
  number: number | null
  repo: string
  branch: string | null
  base: string | null
  counts: Counts
  children: ReactNode
}) {
  const files = counts.files === null ? null : `${counts.files} ${counts.files === 1 ? 'file' : 'files'}`
  return (
    <section
      aria-label={label}
      className="relative overflow-hidden rounded-[20px] border border-solid border-line bg-card py-5 pl-[25px] pr-[22px] shadow-card animate-[otto-arrive_.7s_cubic-bezier(.2,.7,.2,1)_both]"
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-accent" />
      <div className="flex items-center gap-2">
        <Glyph d={IC.pr} className={opened ? 'text-ok' : 'text-accent'} />
        <span className="flex-1 text-[13px] font-medium text-muted">{head}</span>
        <span className={opened ? 'rounded-full bg-ok-bg px-2.5 py-[3px] text-xs font-medium text-ok' : 'rounded-full bg-tag px-2.5 py-[3px] text-xs font-medium text-muted'}>
          {badge}
        </span>
      </div>
      <div className="mt-3 text-[21px] leading-[1.2] tracking-[-0.03em] text-balance">
        {title}
        {number !== null && <span className="text-muted"> #{number}</span>}
      </div>
      <div className="mt-1.5 font-mono text-[12.5px] leading-[1.7] text-muted">
        {[repo, branch && (base ? `${branch} → ${base}` : branch)].filter(Boolean).join(' · ')}
      </div>
      {(counts.additions !== null || counts.tests !== null) && (
        <div className="mt-4 flex flex-wrap items-center gap-x-3.5 gap-y-2 border-0 border-t border-solid border-hair pt-3.5">
          {counts.additions !== null && <span className="font-mono text-[13px] text-ok">+{counts.additions}</span>}
          {counts.deletions !== null && <span className="font-mono text-[13px] text-bad">−{counts.deletions}</span>}
          {files && <span className="text-[13px] text-muted">{files}</span>}
          <div className="flex-1" />
          {counts.tests !== null && (
            <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-ok">
              <Glyph d={IC.checkCircle} size={15} width={1.8} />
              {counts.tests} {counts.tests === 1 ? 'test' : 'tests'} passed
            </span>
          )}
        </div>
      )}
      {children}
    </section>
  )
}

/** The pill the card's main action uses: black in light, white in dark, with GitHub's mark. */
export const PR_PILL =
  'inline-flex h-9 items-center gap-2 rounded-full border-0 bg-inv px-[18px] text-[14.5px] text-inv-text hover:text-inv-text hover:opacity-[.82] disabled:opacity-[.72] disabled:hover:opacity-[.72]'

export function passed(tests: TestSummary | { passed: number; failed: number } | null): number | null {
  return tests && !tests.failed ? tests.passed : null
}

/** The payoff: the pull request on GitHub, opened (or updated by a follow-up's push). */
export function PrCard({ pr, onSeeChanges }: { pr: Pr; onSeeChanges: () => void }) {
  return (
    <PrFrame
      label={pr.updated ? 'Pull request updated' : 'Pull request opened'}
      head={pr.updated ? 'Pull request updated' : 'Pull request opened'}
      opened
      badge={pr.updated ? 'Updated' : 'Open'}
      title={pr.title ?? 'Pull request'}
      number={pr.number}
      repo={pr.repo}
      branch={pr.branch}
      base={pr.base}
      counts={{ additions: pr.additions, deletions: pr.deletions, files: pr.files, tests: passed(pr.tests) }}
    >
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <a href={pr.url} target="_blank" rel="noopener noreferrer" className={PR_PILL}>
          <GitHubIcon size={15} />
          View on GitHub
        </a>
        {pr.firstFile && (
          <a
            href="#changes"
            onClick={(e) => {
              e.preventDefault()
              onSeeChanges()
            }}
            className="text-[14.5px]"
          >
            See changes ›
          </a>
        )}
      </div>
    </PrFrame>
  )
}
