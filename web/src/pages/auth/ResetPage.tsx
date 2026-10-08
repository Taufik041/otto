import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api } from '@/api'
import { ApiError, capitalize, messageOf } from '@/api/errors'
import { Lockup, Mark } from '@/components/brand'
import { MIN_PASSWORD } from '@/utils/password'
import { PillInput, Solid } from './SignIn'
import { StrengthMeter } from './StrengthMeter'

/** The link from the reset email: /reset-password?token=... (it lasts an hour, and works once). */
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
    <main className="min-h-full bg-bg">
      <div className="flex h-[52px] items-center bg-bg2 px-5 sm:px-8">
        <Lockup height={22} />
      </div>
      <div className="flex justify-center px-4 pb-20 pt-10 sm:pt-[88px]">
        <section
          aria-labelledby="reset-title"
          className="w-full max-w-[448px] rounded-[20px] bg-card px-6 py-8 text-center shadow-[var(--shadow),0_0_0_1px_var(--hair)] sm:px-10 sm:pb-8 sm:pt-9"
        >
          <div className="flex justify-center">
            <Mark size={40} />
          </div>
          <h1 id="reset-title" className="m-0 mt-4 text-2xl font-normal leading-[1.2] tracking-[-0.03em]">
            Choose a new password
          </h1>
          <p className="mx-auto mb-0 mt-2 max-w-[340px] text-[15px] leading-[1.45] text-muted">
            Every other device is signed out when you change it.
          </p>
          <form noValidate onSubmit={submit} className="mt-6 flex flex-col gap-3 text-left">
            <PillInput
              label="New password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value)
                setError(null)
              }}
              error={error ?? undefined}
            />
            {password && !error && (
              <span className="flex flex-col gap-1.5 px-5">
                <StrengthMeter password={password} />
              </span>
            )}
            <Solid disabled={busy || !token}>Set password and log in</Solid>
          </form>
          <p className="mb-0 mt-5 text-sm">
            <Link to="/login">Ask for a new link</Link>
          </p>
        </section>
      </div>
    </main>
  )
}
