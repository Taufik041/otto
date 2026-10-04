import { useMutation } from '@tanstack/react-query'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { cn } from '@/utils/cn'
import { Glyph, IC } from './icons'
import type { Proposal } from './reduce'

/**
 * Otto's proposed pull request, waiting for the user (Otto never opens one itself): "Create pull
 * request" opens it on GitHub (the card then becomes the PR card, as pr.opened arrives), "Not now"
 * folds it to a quiet line whose link still creates it. Both wait while Otto works.
 */
export function ProposalCard({
  sessionId,
  proposal,
  state,
  live,
}: {
  sessionId: string
  proposal: Proposal
  state: 'proposed' | 'declined'
  /** Otto is working: nothing to create until it finishes */
  live: boolean
}) {
  const mobile = useIsMobile()
  const create = useMutation({ mutationFn: () => api.createPr(sessionId) })
  const decline = useMutation({ mutationFn: () => api.declinePr(sessionId) })
  // after success the card waits for pr.opened, which replaces it; never a second click meanwhile
  const creating = create.isPending || create.isSuccess
  const busy = creating || decline.isPending
  const error = create.error ?? decline.error

  const createButton = (quiet: boolean) => (
    <button
      type="button"
      disabled={live || busy}
      aria-busy={creating}
      onClick={() => create.mutate()}
      className={cn(
        quiet
          ? 'border-0 bg-transparent p-0 text-[13px] text-accent hover:text-accent-h disabled:text-muted'
          : 'inline-flex h-10 items-center justify-center gap-2 rounded-[980px] border-0 bg-accent px-5 text-[15px] text-white hover:bg-accent-h disabled:opacity-50',
        !quiet && mobile && 'w-full',
      )}
    >
      {creating && <Glyph d={IC.spin} size={14} width={2.2} className="animate-spin-slow" />}
      Create pull request
    </button>
  )
  const problem = error && (
    <p role="alert" className="mb-0 mt-2.5 text-sm text-bad">
      {messageOf(error)}
    </p>
  )

  if (state === 'declined') {
    return (
      <div className="pb-1 text-center text-[13px] text-muted animate-rise">
        <span>Pull request not created</span>
        <span aria-hidden="true"> · </span>
        {createButton(true)}
        {live && <span className="block pt-1">Otto is working…</span>}
        {problem}
      </div>
    )
  }

  const files = proposal.files === null ? null : `${proposal.files} ${proposal.files === 1 ? 'file' : 'files'}`
  const tests = proposal.tests && !proposal.tests.failed ? proposal.tests.passed : null
  return (
    <section
      aria-label="Ready for review"
      className="rounded-[22px] border border-solid border-line bg-card px-[22px] pb-5 pt-[22px] shadow-card animate-rise"
    >
      <div className="flex items-center gap-2">
        <Glyph d={IC.pr} className="text-muted" />
        <span className="flex-1 text-[13px] font-medium text-muted">Ready for review</span>
      </div>
      <div className="mt-3.5 text-[22px] font-semibold leading-[1.2] tracking-[-0.018em] text-balance">{proposal.title}</div>
      <div className="mt-2 font-mono text-[12.5px] text-muted">
        {[proposal.repo, [proposal.head, proposal.base].filter(Boolean).join(' → ')].filter(Boolean).join(' · ')}
      </div>
      {(proposal.additions !== null || tests !== null) && (
        <div className="mt-[18px] flex flex-wrap items-center gap-x-3.5 gap-y-2 border-0 border-t border-solid border-hair pt-4">
          {proposal.additions !== null && <span className="font-mono text-[13px] text-ok">+{proposal.additions}</span>}
          {proposal.deletions !== null && <span className="font-mono text-[13px] text-bad">−{proposal.deletions}</span>}
          {files && <span className="text-[13px] text-muted">{files}</span>}
          <div className="flex-1" />
          {tests !== null && (
            <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-ok">
              <Glyph d={IC.checkCircle} size={15} width={1.8} />
              {tests} {tests === 1 ? 'test' : 'tests'} passed
            </span>
          )}
        </div>
      )}
      <div className={cn('mt-[18px] flex items-center gap-x-3 gap-y-2.5', mobile ? 'flex-col items-stretch' : 'flex-wrap')}>
        {createButton(false)}
        <button
          type="button"
          disabled={live || busy}
          onClick={() => decline.mutate()}
          className={cn(
            'h-10 rounded-[980px] border border-solid border-line bg-transparent px-5 text-[15px] text-text hover:bg-hover disabled:opacity-50',
            mobile && 'w-full',
          )}
        >
          Not now
        </button>
      </div>
      {live && <p className="mb-0 mt-2.5 text-[13px] text-muted">Otto is working…</p>}
      {problem}
    </section>
  )
}
