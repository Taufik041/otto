import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { client } from '@/api'
import { needsOnboarding, takeReturn } from '@/auth/auth'

/** GitHub sign-in (or linking) ends here with a new refresh cookie: swap it for an access token,
 *  then go where the flow started, to onboarding for a new account, or home. A new account the
 *  gateway refused (?error=invite_only or paused) goes to the dialog in that state instead. */
export function CallbackPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const refused = params.get('error')
  useEffect(() => {
    if (refused === 'invite_only' || refused === 'paused') {
      navigate(`/login?error=${refused}`, { replace: true })
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
  }, [navigate, refused])
  return <div className="h-full bg-bg" aria-busy="true" />
}
