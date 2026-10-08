import { BarChart3, ChevronLeft, ChevronRight, Cpu, Palette, User } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router'
import { useMe } from '@/auth/auth'
import { Avatar } from '@/components/Avatar'
import { RepoIcon } from '@/components/icons'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { LegalLinks } from '../legal/LegalLinks'
import { AccountPage } from './AccountPage'
import { AppearancePage } from './AppearancePage'
import { GitHubPage } from './GitHubPage'
import { ModelsPage } from './ModelsPage'
import { UsagePage } from './UsagePage'

const PAGES = [
  { id: 'account', label: 'Account', Icon: User, Page: AccountPage },
  { id: 'github', label: 'GitHub', Icon: RepoIcon, Page: GitHubPage },
  { id: 'models', label: 'Models', Icon: Cpu, Page: ModelsPage },
  { id: 'usage', label: 'Usage', Icon: BarChart3, Page: UsagePage },
  { id: 'appearance', label: 'Appearance', Icon: Palette, Page: AppearancePage },
] as const

/** Settings: a left nav on desktop; on phones a list (/settings) that drills into each section. */
export function SettingsLayout() {
  const { section } = useParams()
  const mobile = useIsMobile()
  const navigate = useNavigate()
  const page = PAGES.find((p) => p.id === section)

  if (section && !page) return <Navigate to="/settings/account" replace />
  if (!page && !mobile) return <Navigate to="/settings/account" replace />

  return (
    <div className="flex h-full bg-bg">
      {!mobile && (
        <nav aria-label="Settings" className="flex w-[260px] shrink-0 flex-col border-0 border-r border-solid border-line bg-bg2 px-3 py-[18px]">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-1 self-start border-0 bg-transparent px-2 py-1.5 text-sm text-accent"
          >
            <ChevronLeft size={14} strokeWidth={2} />
            Back to chats
          </button>
          <h1 className="mx-3 mb-4 mt-[18px] text-[28px] font-normal tracking-[-0.03em]">Settings</h1>
          {PAGES.map(({ id, label, Icon }) => {
            const on = id === section
            return (
              <button
                key={id}
                type="button"
                aria-current={on ? 'page' : undefined}
                onClick={() => navigate(`/settings/${id}`)}
                className="flex w-full items-center gap-3 rounded-[10px] border-0 px-3 py-[9px] text-left text-[15px] text-text hover:bg-sel"
                style={{ background: on ? 'var(--sel)' : undefined, fontWeight: on ? 500 : 400 }}
              >
                <Icon size={17} strokeWidth={1.6} className="text-muted" />
                {label}
              </button>
            )
          })}
          <LegalLinks className="mt-auto px-3" />
        </nav>
      )}

      <div className="relative flex min-w-0 flex-1 flex-col">
        {mobile && (
          <div className="flex h-14 shrink-0 items-center gap-1.5 border-0 border-b border-solid border-hair bg-nav px-2 backdrop-blur-[20px] backdrop-saturate-[1.8]">
            <button
              type="button"
              onClick={() => navigate(page ? '/settings' : '/')}
              className="flex items-center gap-0.5 border-0 bg-transparent p-2 text-base text-accent"
            >
              <ChevronLeft size={18} strokeWidth={2} />
              {page ? 'Settings' : 'Chats'}
            </button>
            <div className="mr-16 flex-1 text-center text-base font-medium">{page?.label ?? ''}</div>
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-y-auto">
          {page ? (
            <div
              key={page.id}
              className="flex max-w-[720px] flex-col gap-7 animate-rise"
              style={{ padding: mobile ? '20px 16px 48px' : '56px 64px 80px' }}
            >
              {!mobile && <h2 className="m-0 text-[32px] font-normal tracking-[-0.03em]">{page.label}</h2>}
              <page.Page />
            </div>
          ) : (
            <MobileRoot onPick={(id) => navigate(`/settings/${id}`)} />
          )}
        </main>
      </div>
    </div>
  )
}

function MobileRoot({ onPick }: { onPick: (id: string) => void }) {
  const me = useMe()
  return (
    <div className="flex flex-col gap-5 px-4 pb-10 pt-5">
      <div className="flex items-center gap-3.5 px-1 pt-1">
        <Avatar name={me.name} email={me.email} url={me.avatar_url} size={52} />
        <span className="min-w-0">
          <span className="block truncate text-[19px] font-normal tracking-[-0.03em]">{me.name}</span>
          {me.email && <span className="block truncate text-sm text-muted">{me.email}</span>}
        </span>
      </div>
      <div className="overflow-hidden rounded-2xl bg-bg2">
        {PAGES.map(({ id, label, Icon }, i) => (
          <button
            key={id}
            type="button"
            onClick={() => onPick(id)}
            className="flex w-full items-center gap-3.5 border-0 bg-transparent px-4 py-[13px] text-left text-base text-text"
            style={{ borderTop: i ? '1px solid var(--hair)' : 'none' }}
          >
            <Icon size={19} strokeWidth={1.6} className="text-muted" />
            <span className="flex-1">{label}</span>
            <ChevronRight size={14} strokeWidth={2} className="text-muted" />
          </button>
        ))}
      </div>
      <LegalLinks className="justify-center" />
    </div>
  )
}
