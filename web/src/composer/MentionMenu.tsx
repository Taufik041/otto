import { Lock } from 'lucide-react'
import { Link } from 'react-router'
import type { Repo } from '@/api/types'
import { GitHubIcon } from '@/components/brand'
import { RepoIcon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { updatedAgo } from '@/utils/format'
import { ownerOf, shortName } from '@/utils/mention'

/** The @ popover's list of repos (already filtered); the keyboard is handled by the textarea. */
export function MentionMenu({
  repos,
  query,
  active,
  mobile,
  onPick,
  onHover,
}: {
  repos: Repo[]
  query: string
  active: number
  mobile: boolean
  onPick: (repo: Repo) => void
  onHover: (index: number) => void
}) {
  const rowPad = mobile ? '13px 12px' : '9px 12px'
  return (
    <>
      <div className="px-3 pb-1.5 pt-2 text-xs font-medium text-muted" id="mention-label">
        Repositories
      </div>
      <div role="listbox" id="mention-list" aria-labelledby="mention-label" className="max-h-[300px] overflow-y-auto">
        {repos.map((r, i) => (
          <div
            key={r.full_name}
            id={`mention-${i}`}
            role="option"
            aria-selected={i === active}
            onClick={() => onPick(r)}
            onMouseEnter={() => onHover(i)}
            className="flex w-full cursor-pointer items-center gap-3 rounded-[10px] leading-[normal] text-text"
            style={{ padding: rowPad, background: i === active ? 'var(--sel)' : 'transparent' }}
          >
            <RepoIcon size={16} strokeWidth={1.6} className="shrink-0 text-muted" />
            <span className="min-w-0 flex-1 truncate text-[15px]">
              <span className="text-muted">{ownerOf(r.full_name)}/</span>
              <span className="font-medium">{shortName(r.full_name)}</span>
            </span>
            {r.private && <Lock size={13} strokeWidth={1.8} aria-label="Private" className="shrink-0 text-muted" />}
            <span className="shrink-0 text-[12.5px] text-muted">{updatedAgo(r.updated_at)}</span>
          </div>
        ))}
      </div>
      {repos.length === 0 && <div className="px-3 py-3.5 text-sm text-muted">No repos match “{query}”.</div>}
      <div className="mt-1.5 flex items-center gap-2 border-0 border-t border-solid border-hair px-3 pb-1.5 pt-2.5">
        <Link to="/settings/github" className="flex-1 text-sm">
          Manage repositories
        </Link>
        {!mobile && <span className="text-xs text-muted">↑↓ to move · ↵ to select</span>}
      </div>
    </>
  )
}

/** No repos to mention: connect GitHub, or install the App on a repo. Both go through the App's
 *  install page on GitHub, which also links the GitHub account. */
export function NoRepos({ linked, busy, onInstall }: { linked: boolean; busy: boolean; onInstall: () => void }) {
  return (
    <div className="px-[18px] pb-[18px] pt-[22px] text-center">
      <GitHubIcon size={28} className="mx-auto text-text" />
      <div className="mt-3 text-base font-medium">
        {linked ? 'Install Otto on a repository' : 'Connect GitHub to mention repos'}
      </div>
      <div className="mt-1 text-sm text-muted">Otto only sees the repos you choose.</div>
      <Button variant="primary" className="mt-4 gap-2" disabled={busy} onClick={onInstall}>
        <GitHubIcon size={16} />
        {linked ? 'Install on repositories' : 'Connect GitHub'}
      </Button>
    </div>
  )
}
