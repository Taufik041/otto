import type { Issue } from '@/api/types'
import { Glyph, IC } from '@/chat/icons'

/** The # popover's list of a repo's open issues (already filtered); the keyboard is handled by the
 *  textarea, as with the @ picker. */
export function IssueMenu({
  repo,
  issues,
  query,
  active,
  mobile,
  onPick,
  onHover,
}: {
  repo: string
  issues: Issue[]
  query: string
  active: number
  mobile: boolean
  onPick: (issue: Issue) => void
  onHover: (index: number) => void
}) {
  const rowPad = mobile ? '13px 12px' : '9px 12px'
  return (
    <>
      <div className="truncate px-3 pb-1.5 pt-2 text-xs font-medium text-muted" id="issue-label">
        Open issues in {repo}
      </div>
      <div role="listbox" id="issue-list" aria-labelledby="issue-label" className="max-h-[300px] overflow-y-auto">
        {issues.map((issue, i) => (
          <div
            key={issue.number}
            id={`issue-${i}`}
            role="option"
            aria-selected={i === active}
            onClick={() => onPick(issue)}
            onMouseEnter={() => onHover(i)}
            className="flex w-full cursor-pointer items-center gap-3 rounded-[10px] leading-[normal] text-text"
            style={{ padding: rowPad, background: i === active ? 'var(--sel)' : 'transparent' }}
          >
            <Glyph d={IC.issue} size={16} width={1.6} className="shrink-0 text-ok" />
            <span className="shrink-0 font-mono text-[13px] text-muted">#{issue.number}</span>
            <span className="min-w-0 flex-1 truncate text-[15px]">{issue.title}</span>
            {issue.labels.slice(0, mobile ? 1 : 2).map((l) => (
              <span key={l} className="max-w-[110px] shrink-0 truncate rounded-full bg-tag px-2 py-px text-[12px] text-muted">
                {l}
              </span>
            ))}
          </div>
        ))}
      </div>
      {issues.length === 0 && (
        <div className="px-3 py-3.5 text-sm text-muted">{query ? `No open issues match “${query}”.` : 'No open issues.'}</div>
      )}
      {!mobile && (
        <div className="mt-1.5 flex items-center justify-end border-0 border-t border-solid border-hair px-3 pb-1.5 pt-2.5">
          <span className="text-xs text-muted">↑↓ to move · ↵ to select</span>
        </div>
      )}
    </>
  )
}
