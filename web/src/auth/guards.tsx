import { useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { ConfirmEmailPage } from '@/pages/auth/ConfirmEmailPage'
import { needsConfirmation, safeNext, useAuth, type AuthStatusSettled } from './auth'

function Booting() {
  return <div className="h-full bg-bg" aria-busy="true" />
}

/** Signed-in pages: while the session is restored show nothing; signed out, go to /login and
 *  come back afterwards; an email that isn't confirmed yet sees "Confirm your email" instead. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, user } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <Booting />
  if (status === 'signedOut') {
    const here = loc.pathname + loc.search
    const qs = here !== '/' ? `?${new URLSearchParams({ next: here })}` : ''
    return <Navigate to={`/login${qs}`} replace />
  }
  if (user && needsConfirmation(user)) return <ConfirmEmailPage email={user.email!} />
  return <>{children}</>
}

/** Sign-in and sign-up: a visitor who arrives signed in goes to the app instead. Signing in on
 *  the page itself doesn't count: the page then navigates (to ?next=, or onboarding) on its own. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const loc = useLocation()
  const arrived = useRef<AuthStatusSettled | null>(null)
  if (status === 'loading') return <Booting />
  arrived.current ??= status
  if (arrived.current === 'signedIn') {
    return <Navigate to={safeNext(new URLSearchParams(loc.search).get('next'))} replace />
  }
  return <>{children}</>
}
