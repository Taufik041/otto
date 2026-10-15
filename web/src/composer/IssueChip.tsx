import { X } from 'lucide-react'
import type { Issue } from '@/api/types'
import { Glyph, IC } from '@/chat/icons'

/** The composer's chip for the issue picked with #: its number and title, and a remove button. */
export function IssueChip({ issue, onRemove }: { issue: Issue; onRemove: () => void }) {
  return (
    <span
      title={issue.title}
      className="inline-flex h-7 min-w-0 max-w-full shrink items-center gap-1 rounded-lg bg-accent-bg pl-[9px] pr-1.5 text-[15px] font-medium text-accent"
    >
      <Glyph d={IC.issue} size={13} width={1.9} className="shrink-0" />
      <span className="shrink-0">#{issue.number}</span>
      <span className="min-w-0 max-w-[260px] truncate font-normal">{issue.title}</span>
      <button
        type="button"
        title="Remove"
        aria-label={`Remove issue #${issue.number}`}
        onClick={onRemove}
        className="flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border-0 bg-transparent p-0 text-inherit"
      >
        <X size={11} strokeWidth={2.4} />
      </button>
    </span>
  )
}
