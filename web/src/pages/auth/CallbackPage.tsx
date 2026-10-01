import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { client } from '@/api'
import { needsOnboarding, takeReturn } from '@/auth/auth'

/** GitHub sign-in (or linking) ends here with a new refresh cookie: swap it for an access token,
 *  then go where the flow started, to onboarding for a new account, or home. */
export function CallbackPage() {
  const navigate = useNavigate()
  useEffect(() => {
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
  }, [navigate])
  return <div className="h-full bg-bg" aria-busy="true" />
}
