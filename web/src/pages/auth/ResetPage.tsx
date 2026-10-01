import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api } from '@/api'
import { capitalize, messageOf, ApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { MIN_PASSWORD } from '@/utils/password'
import { AuthCard, AuthTitle, Banner } from './AuthCard'
import { StrengthMeter } from './StrengthMeter'

/** The link from the reset email: /reset-password?token=... */
export function ResetPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(token ? null : 'This reset link is incomplete. Ask for a new one.')

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters.`)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.reset(token, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400 ? capitalize(err.message) + '.' : messageOf(err))
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <AuthTitle>Choose a new password.</AuthTitle>
      {error && <Banner>{error}</Banner>}
      <form className="flex flex-col gap-3.5" onSubmit={submit} noValidate>
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          note={password ? <span className="flex flex-col gap-1.5"><StrengthMeter password={password} /></span> : undefined}
        />
        <Button type="submit" size="lg" className="mt-1.5" disabled={busy || !token || !password}>
          Set password and sign in
        </Button>
      </form>
      <p className="mb-0 mt-6 text-center text-sm">
        <Link to="/forgot-password">Ask for a new link</Link>
      </p>
    </AuthCard>
  )
}
