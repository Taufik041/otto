import { Glyph, IC } from './icons'
import type { PrCard as Pr } from './reduce'

/** The payoff: the pull request, as a finished object. */
export function PrCard({ pr, onSeeChanges }: { pr: Pr; onSeeChanges: () => void }) {
  const files = pr.files === null ? null : `${pr.files} ${pr.files === 1 ? 'file' : 'files'}`
  return (
    <div className="rounded-[22px] border border-solid border-line bg-card px-[22px] pb-5 pt-[22px] shadow-card animate-[otto-arrive_.7s_cubic-bezier(.2,.7,.2,1)_both]">
      <div className="flex items-center gap-2">
        <Glyph d={IC.pr} className="text-ok" />
        <span className="flex-1 text-[13px] font-medium text-muted">{pr.updated ? 'Pull request updated' : 'Pull request opened'}</span>
        <span className="rounded-full bg-ok-bg px-2.5 py-[3px] text-xs font-medium text-ok">Open</span>
      </div>
      <div className="mt-3.5 text-[22px] font-semibold leading-[1.2] tracking-[-0.018em] text-balance">
        {pr.title ?? 'Pull request'} <span className="font-normal text-muted">#{pr.number}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 font-mono text-[12.5px] text-muted">
        <span>{pr.repo}</span>
        {pr.branch && (
          <>
            <span>·</span>
            <span>
              {pr.branch}
              {pr.base && ` → ${pr.base}`}
            </span>
          </>
        )}
      </div>
      {(pr.additions !== null || pr.tests) && (
        <div className="mt-[18px] flex flex-wrap items-center gap-x-3.5 gap-y-2 border-0 border-t border-solid border-hair pt-4">
          {pr.additions !== null && <span className="font-mono text-[13px] text-ok">+{pr.additions}</span>}
          {pr.deletions !== null && <span className="font-mono text-[13px] text-bad">−{pr.deletions}</span>}
          {files && <span className="text-[13px] text-muted">{files}</span>}
          <div className="flex-1" />
          {pr.tests && (
            <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-ok">
              <Glyph d={IC.checkCircle} size={15} width={1.8} />
              {pr.tests.passed} {pr.tests.passed === 1 ? 'test' : 'tests'} passed
            </span>
          )}
        </div>
      )}
      <div className="mt-[18px] flex flex-wrap items-center gap-x-[18px] gap-y-3">
        <a
          href={pr.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-10 items-center gap-[7px] rounded-[980px] bg-accent px-5 text-[15px] text-white hover:bg-accent-h hover:text-white"
        >
          View on GitHub
          <Glyph d={IC.ext} size={13} width={2} />
        </a>
        {pr.firstFile && (
          <a
            href="#changes"
            onClick={(e) => {
              e.preventDefault()
              onSeeChanges()
            }}
            className="text-[15px]"
          >
            See changes ›
          </a>
        )}
      </div>
    </div>
  )
}
