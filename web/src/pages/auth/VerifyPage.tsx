import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api, client } from '@/api'
import { ApiError, capitalize, messageOf } from '@/api/errors'
import { needsConfirmation, needsOnboarding, useAuth } from '@/auth/auth'
import { Page } from './ConfirmEmailPage'

/** The link from "Confirm your email for Otto": /verify-email?token=... (24 hours, once). It
 *  confirms the email and signs in; someone signed in and confirmed already just lands on the app. */
export function VerifyPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { status, user } = useAuth()
  const token = params.get('token') ?? ''
  const [error, setError] = useState<string | null>(token ? null : 'This confirmation link is incomplete.')
  const asked = useRef(false) // the link works once: ask once, even when an effect runs twice
  const confirmed = status === 'signedIn' && user !== null && !needsConfirmation(user)

  useEffect(() => {
    if (status === 'loading' || asked.current) return
    asked.current = true
    if (confirmed) return void navigate('/', { replace: true })
    if (!token) return
    api
      .verifyEmail(token)
      .then(() => {
        const me = client.getState().user
        navigate(me && needsOnboarding(me) ? '/welcome' : '/', { replace: true })
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 400 ? `${capitalize(e.message)}.` : messageOf(e)))
  }, [status, confirmed, token, navigate])

  if (!error) return <div className="h-full bg-bg" aria-busy="true" />
  return (
    <Page labelledBy="verify-title">
      <h1 id="verify-title" className="m-0 mt-4 text-2xl font-normal leading-[1.2] tracking-[-0.03em]">
        That link didn’t work
      </h1>
      <p role="alert" className="mx-auto mb-0 mt-2 max-w-[340px] text-[15px] leading-[1.45] text-muted text-pretty">
        {error}
      </p>
      <p className="mb-0 mt-5 text-sm">
        {status === 'signedIn' ? <Link to="/">Back to Otto</Link> : <Link to="/login">Log in to get a new link</Link>}
      </p>
    </Page>
  )
}
