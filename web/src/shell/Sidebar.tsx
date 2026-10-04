import { useQueryClient } from '@tanstack/react-query'
import { BarChart3, ChevronsUpDown, Ellipsis, LogOut, Palette, PanelLeft, Search, Settings, SquarePen, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { client } from '@/api'
import { useSessions } from '@/api/queries'
import type { SessionSummary } from '@/api/types'
import { useMe } from '@/auth/auth'
import { Avatar } from '@/components/Avatar'
import { Lockup, Mark } from '@/components/brand'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/utils/cn'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { groupSessions } from '@/utils/sessions'
import { DeleteChatDialog } from './DeleteChatDialog'
import { ThemeSwitch } from './ThemeSwitch'

const ICON = { size: 18, strokeWidth: 1.7 } as const

/** The left sidebar: the full one, or (desktop) the 64px rail when collapsed. */
export function Sidebar({
  mobile,
  collapsed,
  onToggle,
  onNavigate,
}: {
  mobile: boolean
  collapsed: boolean
  /** desktop: collapse or expand; mobile: close the drawer */
  onToggle: () => void
  /** a row or New chat was picked (closes the drawer) */
  onNavigate: () => void
}) {
  const [deleting, setDeleting] = useState<SessionSummary | null>(null)
  const navigate = useNavigate()
  const newChat = () => {
    onNavigate()
    navigate('/')
  }

  return (
    <>
      {collapsed && !mobile ? (
        <div className="flex flex-1 flex-col items-center gap-1.5 pb-3 pt-3.5">
          <RailButton title="Open sidebar" onClick={onToggle}>
            <Mark size={24} />
          </RailButton>
          <RailButton title="New chat" onClick={newChat}>
            <SquarePen {...ICON} />
          </RailButton>
          <RailButton title="Search chats" onClick={onToggle}>
            <Search {...ICON} />
          </RailButton>
          <div className="flex-1" />
          <ProfileMenu compact />
        </div>
      ) : (
        <Expanded mobile={mobile} onToggle={onToggle} onNewChat={newChat} onNavigate={onNavigate} onDelete={setDeleting} />
      )}
      <DeleteChatDialog chat={deleting} onOpenChange={(open) => !open && setDeleting(null)} />
    </>
  )
}

function RailButton({ title, onClick, children }: { title: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className="flex size-10 items-center justify-center rounded-[10px] border-0 bg-transparent text-text hover:bg-sel"
    >
      {children}
    </button>
  )
}

function Expanded({
  mobile,
  onToggle,
  onNewChat,
  onNavigate,
  onDelete,
}: {
  mobile: boolean
  onToggle: () => void
  onNewChat: () => void
  onNavigate: () => void
  onDelete: (s: SessionSummary) => void
}) {
  const [q, setQ] = useState('')
  const sessions = useSessions()
  const { id: current } = useParams()
  const groups = useMemo(() => {
    const query = q.trim().toLowerCase()
    const list = (sessions.data ?? []).filter((s) => !query || s.title.toLowerCase().includes(query))
    return groupSessions(list)
  }, [sessions.data, q])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center pb-2.5 pl-[18px] pr-3 pt-4">
        <Link to="/" onClick={onNavigate} aria-label="Otto home" className="flex">
          <Lockup height={22} />
        </Link>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onToggle}
          title={mobile ? 'Close' : 'Collapse sidebar'}
          aria-label={mobile ? 'Close' : 'Collapse sidebar'}
          className="flex size-[34px] items-center justify-center rounded-[9px] border-0 bg-transparent text-muted hover:bg-sel"
        >
          {mobile ? <X size={18} strokeWidth={1.6} /> : <PanelLeft size={18} strokeWidth={1.6} />}
        </button>
      </div>

      <div className="flex shrink-0 flex-col gap-2 px-3 pb-2.5 pt-1.5">
        <button
          type="button"
          onClick={onNewChat}
          className="flex h-10 items-center gap-2.5 rounded-xl border border-solid border-line bg-card px-3 text-[14.5px] font-medium text-text transition-colors duration-200 hover:bg-hover"
        >
          <SquarePen size={16} strokeWidth={1.7} />
          New chat
        </button>
        <label className="flex h-9 items-center gap-2 rounded-[10px] bg-sel px-[11px]">
          <Search size={15} strokeWidth={1.7} className="shrink-0 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search chats"
            aria-label="Search chats"
            className="min-w-0 flex-1 border-0 bg-transparent text-sm text-text outline-none"
          />
        </label>
      </div>

      <nav aria-label="Chats" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-1">
        {groups.map((g) => (
          <section key={g.label}>
            <h2 className="m-0 px-3 pb-1.5 pt-4 text-xs font-semibold text-muted">{g.label}</h2>
            {g.sessions.map((s) => (
              <ChatRow key={s.id} chat={s} current={s.id === current} onPick={onNavigate} onDelete={() => onDelete(s)} />
            ))}
          </section>
        ))}
        {sessions.isSuccess && groups.length === 0 && (
          <div className="px-3 py-6 text-[13px] text-muted">{q.trim() ? 'No chats match.' : 'No chats yet.'}</div>
        )}
      </nav>

      <div className="shrink-0 border-0 border-t border-solid border-hair px-2 pb-3 pt-2">
        <ProfileMenu />
      </div>
    </div>
  )
}

// the dot is "needs your attention": working, or a turn that ended since you last saw the chat
const DOT_COLOR = { working: 'var(--warn)', done: 'var(--ok)', failed: 'var(--bad)' } as const
const DOT_LABEL = { working: 'Working', done: 'Done', failed: 'Failed' } as const

function ChatRow({
  chat,
  current,
  onPick,
  onDelete,
}: {
  chat: SessionSummary
  current: boolean
  onPick: () => void
  onDelete: () => void
}) {
  const dot = chat.attention
  const steady = useMediaQuery('(prefers-reduced-motion: reduce)')
  return (
    <div
      className={cn(
        'group relative flex items-start rounded-[10px] transition-colors duration-150 hover:bg-sel has-[[data-state=open]]:bg-sel',
        current && 'bg-sel',
      )}
    >
      <Link
        to={`/c/${chat.id}`}
        onClick={onPick}
        aria-current={current ? 'page' : undefined}
        className="flex min-w-0 flex-1 items-start gap-2.5 py-2 pl-3 pr-9 leading-normal text-text hover:text-text [&_span]:leading-[normal]"
      >
        <span
          className={cn('mt-2 size-[7px] shrink-0 rounded-full', dot === 'working' && !steady && 'animate-pulse-dot')}
          style={{ background: dot ? DOT_COLOR[dot] : 'transparent' }}
          role={dot ? 'img' : undefined}
          aria-label={dot ? DOT_LABEL[dot] : undefined}
        />
        <span className="min-w-0 flex-1">
          <span className={cn('block truncate text-sm', current ? 'font-medium' : 'font-normal')}>{chat.title}</span>
          {chat.repo && <span className="block truncate text-xs text-muted">{chat.repo}</span>}
        </span>
      </Link>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Options for ${chat.title}`}
            className="absolute right-1.5 top-1.5 flex size-7 items-center justify-center rounded-lg border-0 bg-transparent text-muted opacity-0 hover:bg-sel hover:text-text focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
          >
            <Ellipsis size={16} strokeWidth={2} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[180px]">
          <DropdownMenuItem variant="danger" onSelect={onDelete}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** The user button and its menu: Settings, Usage, Theme, Sign out. */
export function ProfileMenu({ compact = false }: { compact?: boolean }) {
  const me = useMe()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const signOut = async () => {
    await client.logout()
    qc.clear()
    navigate('/login', { replace: true })
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {compact ? (
          <button type="button" title={me.name} aria-label="Account menu" className="rounded-full border-0 bg-transparent p-0">
            <Avatar name={me.name} email={me.email} url={me.avatar_url} size={34} />
          </button>
        ) : (
          <button
            type="button"
            aria-label="Account menu"
            className="flex w-full items-center gap-2.5 rounded-xl border-0 bg-transparent px-2.5 py-2 text-left text-text hover:bg-sel data-[state=open]:bg-sel"
          >
            <Avatar name={me.name} email={me.email} url={me.avatar_url} size={32} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{me.name}</span>
              <span className="block truncate text-xs text-muted">
                {me.github_login ? `@${me.github_login}` : (me.email ?? '')}
              </span>
            </span>
            <ChevronsUpDown size={14} strokeWidth={1.7} className="text-muted" />
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" sideOffset={8} className="w-[252px] rounded-2xl">
        {me.email && <DropdownMenuLabel>{me.email}</DropdownMenuLabel>}
        <DropdownMenuItem onSelect={() => navigate('/settings/account')}>
          <Settings strokeWidth={1.5} />
          Settings
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/usage')}>
          <BarChart3 strokeWidth={1.8} />
          Usage
        </DropdownMenuItem>
        <div className="flex items-center gap-2.5 py-[7px] pl-3 pr-2">
          <Palette size={16} strokeWidth={1.5} className="text-muted" />
          <span className="flex-1 text-[14.5px]">Theme</span>
          <ThemeSwitch />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={signOut}>
          <LogOut strokeWidth={1.6} />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
