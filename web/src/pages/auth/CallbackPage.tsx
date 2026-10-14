import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { client } from '@/api'
import { needsOnboarding, takeReturn } from '@/auth/auth'

/** GitHub sign-in (or linking) ends here with a new refresh cookie: swap it for an access token,
 *  then go where the flow started, to onboarding for a new account, or home. An ?error=<code>
 *  goes to the dialog instead, which says why. */
export function CallbackPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const refused = params.get('error')
  const login = params.get('login')
  useEffect(() => {
    if (refused) {
      navigate(`/login?${new URLSearchParams({ error: refused, ...(login ? { login } : {}) })}`, { replace: true })
      return
    }
    let live = true
    client
      .refresh()
      .then((body) => {
        if (!live) return
        if (!body) return navigate('/login?error=callback', { replace: true })
        navigate(takeReturn() ?? (needsOnboarding(body.user) ? '/welcome' : '/'), { replace: true })
      })
      .catch(() => live && navigate('/login?error=callback', { replace: true }))
    return () => {
      live = false
    }
  }, [navigate, refused, login])
  return <div className="h-full bg-bg" aria-busy="true" />
}
