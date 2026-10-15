import { GitHubIcon } from '@/components/brand'
import { CodeLine } from './Code'
import { languageOf } from './diff'
import { useTokens } from './highlight'
import { Glyph, IC } from './icons'
import { Markdown } from './Markdown'
import { PR_PILL, PrFrame } from './PrCard'
import type { ReviewComment, ReviewPr, Review } from './reduce'

const BADGE = { reviewing: 'Reviewing', reviewed: 'Reviewed', posted: 'Posted on GitHub', failed: 'Not posted' } as const

/** A review chat's pull request: repo, #number, title and a link, in the PR card's frame. */
export function ReviewPrCard({ pr, state, tokens = null }: { pr: ReviewPr; state: keyof typeof BADGE; tokens?: number | null }) {
  const files = pr.totalFiles !== null && pr.reviewedFiles < pr.totalFiles ? `${pr.reviewedFiles} of ${pr.totalFiles} files reviewed` : null
  return (
    <PrFrame
      label={`Pull request #${pr.number}`}
      head={pr.requestedBy ? `Review requested by @${pr.requestedBy}` : 'Automatic review'}
      opened={state === 'posted'}
      badge={BADGE[state]}
      title={pr.title}
      number={pr.number}
      repo={pr.repo}
      branch={pr.head}
      base={pr.base}
      counts={{ additions: pr.additions, deletions: pr.deletions, files: pr.totalFiles, tests: null }}
    >
      {(files || tokens !== null) && (
        <div className="mt-2 text-[12.5px] text-muted">
          {[files, tokens !== null && `${tokens.toLocaleString('en-US')} tokens`].filter(Boolean).join(' · ')}
        </div>
      )}
      {pr.url && (
        <div className="mt-4">
          <a href={pr.url} target="_blank" rel="noopener noreferrer" className={PR_PILL}>
            <GitHubIcon size={15} />
            Open pull request
          </a>
        </div>
      )}
    </PrFrame>
  )
}

/** The lines a comment sits on (its line last), colored like the workspace's diffs. */
function Excerpt({ c }: { c: ReviewComment }) {
  const tokens = useTokens(c.excerpt.map((l) => l.text).join('\n'), languageOf(c.path))
  if (!c.excerpt.length) return null
  return (
    <pre className="m-0 mt-2 overflow-x-auto rounded-[10px] bg-bg2 py-2 font-mono text-[12.5px] leading-[1.65]">
      {c.excerpt.map((l, i) => (
        <div
          key={l.line}
          data-added={l.added || undefined}
          className={`flex whitespace-pre pr-3 ${l.line === c.line ? 'bg-sel' : ''} ${l.added ? 'text-ok' : ''}`}
        >
          <span className="w-12 shrink-0 select-none pr-3 text-right text-ter">{l.line}</span>
          <span className="w-3 shrink-0 select-none text-ter">{l.added ? '+' : ' '}</span>
          <span className="text-text">
            <CodeLine text={l.text} tokens={tokens?.[i]} />
          </span>
        </div>
      ))}
    </pre>
  )
}

/** The review Otto wrote: the summary, then each inline comment with path:line and its code. */
export function ReviewCard({ review }: { review: Review }) {
  const n = review.comments.length
  return (
    <section aria-label="Review" className="rounded-[18px] border border-solid border-line bg-card px-5 py-[18px]">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-medium text-muted">
        <Glyph d={IC.search} size={15} width={1.8} />
        <span className="flex-1">Review</span>
        <span>{n === 0 ? 'No inline comments' : `${n} inline ${n === 1 ? 'comment' : 'comments'}`}</span>
      </div>
      <Markdown text={review.summary} />
      {n > 0 && (
        <ol aria-label="Inline comments" className="m-0 mt-4 flex list-none flex-col gap-3.5 border-0 border-t border-solid border-hair p-0 pt-4">
          {review.comments.map((c) => (
            <li key={`${c.path}:${c.line}`} aria-label={`${c.path}:${c.line}`}>
              <div className="font-mono text-[12.5px] text-muted [overflow-wrap:anywhere]">
                {c.path}:{c.line}
              </div>
              <Excerpt c={c} />
              <div className="mt-2">
                <Markdown text={c.body} />
              </div>
            </li>
          ))}
        </ol>
      )}
      {review.postedUrl ? (
        <a href={review.postedUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-[14.5px]">
          See it on GitHub ›
        </a>
      ) : (
        review.failed && (
          <p role="alert" className="mb-0 mt-3 text-sm text-bad">
            {review.failed}
          </p>
        )
      )}
    </section>
  )
}
