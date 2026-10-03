import { Mail } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { AuthCard, AuthTitle, Banner } from './AuthCard'

export function ForgotPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim()) return setError('Enter your email.')
    setBusy(true)
    setError(null)
    try {
      await api.forgot(email)
      setSent(true)
    } catch (err) {
      setError(messageOf(err))
    }
    setBusy(false)
  }

  if (sent) {
    return (
      <AuthCard>
        <div className="mt-6 flex justify-center">
          <span className="flex size-14 items-center justify-center rounded-full bg-accent-bg text-accent">
            <Mail size={26} strokeWidth={1.6} />
          </span>
        </div>
        <h1 className="mx-0 mb-2.5 mt-[18px] text-center text-[28px] font-semibold tracking-[-0.02em]">Check your inbox.</h1>
        <p className="m-0 text-center text-[15px] text-muted text-pretty">
          We sent a reset link to <span className="text-text">{email}</span>. It expires in an hour.
        </p>
        <p className="mb-0 mt-[26px] text-center text-sm">
          <Link to="/login">‹ Back to sign in</Link>
        </p>
      </AuthCard>
    )
  }

  return (
    <AuthCard>
      <AuthTitle tight>Reset your password.</AuthTitle>
      <p className="mb-[26px] mt-0 text-center text-[15px] text-muted">Enter your email and we'll send you a reset link.</p>
      {error && <Banner>{error}</Banner>}
      <form className="flex flex-col gap-3.5" onSubmit={submit} noValidate>
        <Field label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Button type="submit" size="lg" disabled={busy}>
          Send reset link
        </Button>
      </form>
      <p className="mb-0 mt-6 text-center text-sm">
        <Link to="/login">‹ Back to sign in</Link>
      </p>
    </AuthCard>
  )
}
