import { useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { safeNext, useAuth, type AuthStatusSettled } from './auth'

function Booting() {
  return <div className="h-full bg-bg" aria-busy="true" />
}

/** Signed-in pages: while the session is restored show nothing; signed out, go to /login and
 *  come back afterwards. A ?github_error= travels along so /login can explain it. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <Booting />
  if (status === 'signedOut') {
    const params = new URLSearchParams()
    const here = loc.pathname + loc.search
    const ghError = new URLSearchParams(loc.search).get('github_error')
    if (ghError) params.set('github_error', ghError)
    else if (here !== '/') params.set('next', here)
    const qs = params.toString()
    return <Navigate to={`/login${qs ? `?${qs}` : ''}`} replace />
  }
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
