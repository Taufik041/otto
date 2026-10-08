import { Menu, SquarePen } from 'lucide-react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { Mark } from '@/components/brand'
import { RepoIcon } from '@/components/icons'
import { HEADER_HEIGHT } from '@/components/layers'
import { useShell } from './AppShell'

/** The thin frosted bar over the page: (phones) the drawer button and the mark, then the chat
 *  title, its repo and model, and the page's buttons. */
export function TopBar({
  title,
  repo,
  model,
  bordered = true,
  newChat = false,
  children,
}: {
  title?: string
  repo?: string | null
  model?: string | null
  bordered?: boolean
  /** phones: a New chat button (the empty state has no sidebar visible) */
  newChat?: boolean
  children?: ReactNode
}) {
  const { mobile, openDrawer } = useShell()
  const navigate = useNavigate()
  return (
    <header
      className="absolute inset-x-0 top-0 z-20 flex items-center gap-2.5 border-0 border-b border-solid bg-nav backdrop-blur-[20px] backdrop-saturate-[1.8]"
      style={{
        height: HEADER_HEIGHT,
        boxSizing: 'border-box',
        padding: mobile ? '0 6px' : '0 14px 0 22px',
        borderBottomColor: bordered ? 'var(--hair)' : 'transparent',
      }}
    >
      {mobile && (
        <>
          <button
            type="button"
            onClick={openDrawer}
            title="Chats"
            aria-label="Open chats"
            className="flex size-10 shrink-0 items-center justify-center rounded-[10px] border-0 bg-transparent text-text"
          >
            <Menu size={20} strokeWidth={1.7} />
          </button>
          <Mark size={22} />
        </>
      )}
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        {title && <span className="min-w-0 truncate text-[15px] tracking-[-0.03em]">{title}</span>}
        {repo && !mobile && (
          <span className="inline-flex shrink-0 items-center gap-[5px] rounded-[7px] bg-tag px-2 py-[3px] font-mono text-xs text-text">
            <RepoIcon size={12} className="text-muted" />
            {repo}
          </span>
        )}
        {model && !mobile && <span className="shrink-0 text-[13px] text-muted">{model}</span>}
      </div>
      {children}
      {mobile && newChat && (
        <button
          type="button"
          onClick={() => navigate('/')}
          title="New chat"
          aria-label="New chat"
          className="flex size-10 shrink-0 items-center justify-center rounded-[10px] border-0 bg-transparent text-text"
        >
          <SquarePen size={19} strokeWidth={1.7} />
        </button>
      )}
    </header>
  )
}
