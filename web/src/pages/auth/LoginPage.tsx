import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api } from '@/api'
import { ApiError, messageOf } from '@/api/errors'
import { githubErrorMessage, safeNext } from '@/auth/auth'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { AuthCard, AuthTitle, Banner, Or } from './AuthCard'
import { GitHubSignIn } from './GitHubSignIn'

export function LoginPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [wrong, setWrong] = useState(false)
  const [banner, setBanner] = useState<string | null>(
    githubErrorMessage(params.get('github_error')) ?? (params.get('error') === 'callback' ? "Sign-in didn't finish. Try again." : null),
  )

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setWrong(false)
    setBanner(null)
    try {
      await api.login(email, password)
      navigate(safeNext(params.get('next')), { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setWrong(true)
      else setBanner(messageOf(err))
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <AuthTitle>Welcome back.</AuthTitle>
      {banner && <Banner>{banner}</Banner>}
      <GitHubSignIn onError={setBanner} />
      <Or />
      <form className="flex flex-col gap-3.5" onSubmit={submit} noValidate>
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            setWrong(false)
          }}
          aside={
            <Link to="/forgot-password" className="text-[13px]">
              Forgot password?
            </Link>
          }
          error={wrong ? "That password isn't right. Try again or reset it." : undefined}
        />
        <Button type="submit" size="lg" className="mt-1.5" disabled={busy || !email || !password}>
          Sign in
        </Button>
      </form>
      <p className="mb-0 mt-6 text-center text-sm text-muted">
        New to Otto? <Link to="/signup">Create an account</Link>
      </p>
    </AuthCard>
  )
}
