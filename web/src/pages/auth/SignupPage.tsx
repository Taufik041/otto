import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api } from '@/api'
import { ApiError, capitalize, messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { MIN_PASSWORD } from '@/utils/password'
import { AuthCard, AuthTitle, Banner, Or } from './AuthCard'
import { GitHubSignIn } from './GitHubSignIn'
import { StrengthMeter } from './StrengthMeter'

export function SignupPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [taken, setTaken] = useState(false)
  const [emailError, setEmailError] = useState<string | null>(null)
  const [pwError, setPwError] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTaken(false)
    setEmailError(null)
    setBanner(null)
    if (password.length < MIN_PASSWORD) {
      setPwError(`Use at least ${MIN_PASSWORD} characters.`)
      return
    }
    setBusy(true)
    try {
      await api.signup(name, email, password)
      navigate('/welcome', { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setTaken(true)
      else if (err instanceof ApiError && err.status === 422 && /email/i.test(JSON.stringify(err.body)))
        setEmailError("That doesn't look like an email address.")
      else if (err instanceof ApiError && err.status === 422) setBanner(capitalize(err.message) + '.')
      else setBanner(messageOf(err))
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <AuthTitle>Create your Otto account.</AuthTitle>
      {banner && <Banner>{banner}</Banner>}
      <GitHubSignIn onError={setBanner} />
      <Or />
      <form className="flex flex-col gap-3.5" onSubmit={submit} noValidate>
        <Field label="Name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            setTaken(false)
            setEmailError(null)
          }}
          error={
            taken ? (
              <>
                That email is already registered. <Link to="/login">Sign in instead</Link>
              </>
            ) : (
              emailError ?? undefined
            )
          }
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            setPwError(null)
          }}
          error={pwError ?? undefined}
          note={password ? <span className="flex flex-col gap-1.5"><StrengthMeter password={password} /></span> : undefined}
        />
        <Button type="submit" size="lg" className="mt-1.5" disabled={busy || !name.trim() || !email || !password}>
          Create account
        </Button>
      </form>
      <p className="mb-0 mt-6 text-center text-sm text-muted">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthCard>
  )
}
