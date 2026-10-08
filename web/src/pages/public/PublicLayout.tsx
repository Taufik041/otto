import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useAuth } from '@/auth/auth'
import { Lockup } from '@/components/brand'
import { CONTACT_EMAIL, LANDING_URL } from '@/utils/links'

/** The pages anyone can open (legal, request access, 404): the wash nav and footer around them. */
export function PublicLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  return (
    <div className="flex min-h-full flex-col bg-bg">
      <header className="sticky top-0 z-50 flex h-[52px] shrink-0 items-center gap-6 bg-bg2 px-5 sm:px-8">
        <a href={LANDING_URL} aria-label="Otto home" className="flex">
          <Lockup height={22} />
        </a>
        <div className="flex-1" />
        {status === 'signedIn' ? (
          <Link to="/" className="inline-flex h-8 items-center rounded-full bg-inv px-3.5 text-sm text-inv-text hover:text-inv-text hover:opacity-[.82]">
            Back to chats
          </Link>
        ) : (
          <Link to="/login" className="inline-flex h-8 items-center rounded-full border border-solid border-line px-3.5 text-sm text-text hover:bg-hover hover:text-text">
            Log in
          </Link>
        )}
      </header>
      <div className="flex-1">{children}</div>
      <footer className="border-0 border-t border-solid border-hair bg-bg2">
        <div className="mx-auto flex max-w-[1100px] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-8 text-sm text-muted sm:px-12">
          <span className="mr-auto">Built by Taufik Khan</span>
          <Link to="/legal/terms" className="text-muted hover:text-text">Terms</Link>
          <Link to="/legal/privacy" className="text-muted hover:text-text">Privacy</Link>
          <Link to="/legal/acceptable-use" className="text-muted hover:text-text">Acceptable use</Link>
          <a href={`mailto:${CONTACT_EMAIL}`} className="text-muted hover:text-text">{CONTACT_EMAIL}</a>
        </div>
      </footer>
    </div>
  )
}
