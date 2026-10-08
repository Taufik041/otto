import { useMutation } from '@tanstack/react-query'
import { useContext } from 'react'
import { ApiError, capitalize, messageOf } from '@/api/errors'
import { GitHubIcon } from '@/components/brand'
import { Glyph, IC } from './icons'
import { PrActionsContext } from './prActions'
import { passed, PR_PILL, PrFrame } from './PrCard'
import type { Proposal } from './reduce'

const GITHUB_SAID = "GitHub didn't open the pull request: "

/** Why creating failed, as one plain sentence for the card. */
export function createError(e: unknown): string {
  let reason = messageOf(e)
  if (e instanceof ApiError && e.status === 0) reason = "GitHub didn't respond."
  else if (e instanceof ApiError && e.message.startsWith(GITHUB_SAID)) reason = `GitHub said: ${e.message.slice(GITHUB_SAID.length)}.`
  else if (!/[.!?]$/.test(reason)) reason = `${capitalize(reason)}.`
  return `Otto couldn't open the pull request. ${reason} Your changes are safe, so try again.`
}

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
  const actions = useContext(PrActionsContext)
  const create = useMutation({ mutationFn: () => actions.create(sessionId) })
  const decline = useMutation({ mutationFn: () => actions.decline(sessionId) })
  // after success the card waits for pr.opened, which replaces it; never a second click meanwhile
  const creating = create.isPending || create.isSuccess
  const busy = creating || decline.isPending

  if (state === 'declined') {
    return (
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 py-0.5 text-sm text-muted animate-rise">
        <Glyph d={IC.pr} size={14} />
        <span>Pull request not created ·</span>
        <button
          type="button"
          disabled={live || busy}
          aria-busy={creating}
          onClick={() => create.mutate()}
          className="border-0 bg-transparent p-0 text-sm text-accent hover:text-accent-h disabled:text-muted"
        >
          {creating ? 'Creating pull request…' : 'Create pull request'}
        </button>
        {live && <span className="basis-full">Otto is working…</span>}
        {create.error && (
          <p role="alert" className="m-0 basis-full text-sm text-bad">
            {createError(create.error)}
          </p>
        )}
      </div>
    )
  }

  return (
    <PrFrame
      label="Ready for review"
      head="Ready for review"
      opened={false}
      badge="Not on GitHub yet"
      title={proposal.title}
      number={null}
      repo={proposal.repo}
      branch={proposal.head}
      base={proposal.base}
      counts={{ additions: proposal.additions, deletions: proposal.deletions, files: proposal.files, tests: passed(proposal.tests) }}
    >
      {(create.error || decline.error) && (
        <div role="alert" className="mt-3.5 flex items-start gap-2 rounded-xl bg-bad-bg px-3 py-2.5 text-sm leading-[1.45] text-bad">
          <Glyph d={IC.alert} size={15} width={1.8} className="mt-0.5 shrink-0" />
          <span>{create.error ? createError(create.error) : messageOf(decline.error)}</span>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <button type="button" disabled={live || busy} aria-busy={creating} onClick={() => create.mutate()} className={PR_PILL}>
          {creating ? <Glyph d={IC.spin} size={15} width={2.2} className="animate-spin-slow" /> : <GitHubIcon size={15} />}
          {creating ? 'Creating pull request…' : 'Create pull request'}
        </button>
        {!creating && (
          <button
            type="button"
            disabled={live || busy}
            onClick={() => decline.mutate()}
            className="inline-flex h-9 items-center rounded-full border border-solid border-line bg-transparent px-4 text-[14.5px] text-text hover:bg-hover disabled:opacity-50"
          >
            Not now
          </button>
        )}
      </div>
      {live && <p className="mb-0 mt-2.5 text-[13px] text-muted">Otto is working…</p>}
    </PrFrame>
  )
}
