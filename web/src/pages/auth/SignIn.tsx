import { useId, useState, type ComponentProps, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api, goToGitHub } from '@/api'
import { ApiError, capitalize, messageOf } from '@/api/errors'
import { useHealth } from '@/api/queries'
import { githubErrorMessage, safeNext } from '@/auth/auth'
import { BetaPill, GitHubIcon, Mark } from '@/components/brand'
import { Glyph, IC } from '@/chat/icons'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { cn } from '@/utils/cn'
import { GOOGLE_AUTH, LANDING_URL } from '@/utils/links'
import { MIN_PASSWORD } from '@/utils/password'
import { StrengthMeter } from './StrengthMeter'

/** The steps of "Log in or sign up". Email first: an account means a password next, none means
 *  a name and a password. Invite-only and paused signups have their own steps. */
export type Step = 'email' | 'password' | 'new' | 'inbox' | 'invite' | 'inviteDone' | 'offline'

const TITLE: Record<Step, string> = {
  email: 'Log in or sign up',
  password: 'Welcome back',
  new: 'Create your account',
  inbox: 'Check your inbox',
  invite: 'Otto is invite-only right now.',
  inviteDone: 'Request sent',
  offline: 'Otto is offline right now.',
}

// the same check as the design: a dot and at least two characters after it
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

/** The step a sign-up refusal leads to: 403 invite_only, 503 paused (or the gateway unreachable). */
function refusalStep(e: unknown): Step | null {
  if (!(e instanceof ApiError)) return null
  if (e.status === 0) return 'offline'
  const code = (e.body as { error?: unknown } | null)?.error
  return code === 'invite_only' ? 'invite' : code === 'paused' ? 'offline' : null
}

const sentence = (s: string) => (/[.!?]$/.test(s) ? capitalize(s) : `${capitalize(s)}.`)

/**
 * "Log in or sign up": a centered dialog on desktop, a bottom sheet on phones, or (page) a card
 * on the page itself, for /request-access.
 */
export function SignIn({ page = false, initial }: { page?: boolean; initial?: Step }) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const mobile = useIsMobile()
  const fromCallback = params.get('error')
  const [step, setStep] = useState<Step>(
    initial ?? (fromCallback === 'invite_only' ? 'invite' : fromCallback === 'paused' ? 'offline' : 'email'),
  )
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [who, setWho] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ field: 'email' | 'name' | 'password' | 'who' | 'form'; message: string } | null>(null)
  const [banner, setBanner] = useState<string | null>(
    githubErrorMessage(params.get('github_error')) ?? (fromCallback === 'callback' ? "Sign-in didn't finish. Try again." : null),
  )
  const titleId = useId()
  // "Forgot password?" emails a link: hidden where email isn't set up (GET /health)
  const resetWorks = useHealth().data?.password_reset !== false
  const sheet = mobile && !page

  const go = (next: Step) => {
    setError(null)
    setBusy(false)
    setStep(next)
  }
  const fail = (field: NonNullable<typeof error>['field'], message: string) => {
    setError({ field, message })
    setBusy(false)
  }
  /** Run a request; a refusal that has its own step goes there, anything else is an inline error. */
  async function run(field: NonNullable<typeof error>['field'], fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      const to = refusalStep(e)
      if (to) {
        if (to === 'invite') setWho(email.trim())
        go(to)
      } else fail(field, e instanceof ApiError ? sentence(e.message) : messageOf(e))
    }
  }

  function submitEmail(e: FormEvent) {
    e.preventDefault()
    const value = email.trim()
    if (!EMAIL.test(value)) return fail('email', 'Enter a valid email.')
    return run('email', async () => {
      const { exists } = await api.emailStatus(value)
      setEmail(value)
      go(exists ? 'password' : 'new')
    })
  }

  function submitPassword(e: FormEvent) {
    e.preventDefault()
    if (!password) return fail('password', 'Enter your password.')
    return run('password', async () => {
      try {
        await api.login(email, password)
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return fail('password', "That password isn't right. Try again or reset it.")
        throw err
      }
      navigate(safeNext(params.get('next')), { replace: true })
    })
  }

  function submitNew(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return fail('name', 'Enter your name.')
    if (password.length < MIN_PASSWORD) return fail('password', `Use at least ${MIN_PASSWORD} characters.`)
    return run('password', async () => {
      try {
        await api.signup(name.trim(), email, password)
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          // someone made it meanwhile (another tab): it's a log-in now
          go('password')
          return fail('password', 'That email already has an account. Enter its password.')
        }
        throw err
      }
      navigate('/welcome', { replace: true })
    })
  }

  function forgot() {
    return run('password', async () => {
      await api.forgot(email)
      go('inbox')
    })
  }

  function submitInvite(e: FormEvent) {
    e.preventDefault()
    if (!who.trim()) return fail('who', 'Enter your GitHub username or email.')
    return run('who', async () => {
      await api.requestAccess(who.trim(), note.trim())
      go('inviteDone')
    })
  }

  async function github() {
    setBusy(true)
    try {
      await goToGitHub(() => api.githubUrl('signin'))
    } catch (e) {
      setBanner(messageOf(e))
      setBusy(false)
    }
  }

  const back = () => go('email')
  const sub: Record<Step, string> = {
    email: 'Describe a change. Otto opens the pull request.',
    password: 'Enter your password to continue.',
    new: 'Add your name and choose a password.',
    inbox: `We sent a reset link to ${email}. It expires in 1 hour.`,
    invite: "Tell us who you are and we'll email you when a spot opens.",
    inviteDone: "Thanks. We'll email you when a spot opens, usually within a few days.",
    offline: 'It runs on my own hardware to stay free.',
  }
  const err = (field: NonNullable<typeof error>['field']) => (error?.field === field ? error.message : undefined)

  const card = (
    <div
      role="dialog"
      aria-modal={page ? undefined : true}
      aria-labelledby={titleId}
      onClick={(e) => e.stopPropagation()}
      className="relative w-full bg-card text-center"
      style={{
        maxWidth: sheet ? 'none' : 448,
        borderRadius: sheet ? '24px 24px 0 0' : 20,
        padding: sheet ? '30px 24px 34px' : '36px 40px 32px',
        boxShadow: page ? 'var(--shadow), 0 0 0 1px var(--hair)' : 'var(--pop)',
        animation: sheet ? 'otto-sheet .35s cubic-bezier(.2,.8,.2,1) both' : 'otto-pop .3s ease-out both',
      }}
    >
      {sheet && <div aria-hidden="true" className="mx-auto -mt-3.5 mb-[18px] h-[5px] w-9 rounded-full bg-line" />}
      {!page && (
        <a
          href={LANDING_URL}
          title="Close"
          aria-label="Close"
          className="absolute right-3.5 top-3.5 flex size-[34px] items-center justify-center rounded-full text-muted hover:bg-hover hover:text-muted"
        >
          <Glyph d={IC.x} size={15} width={2} />
        </a>
      )}
      <div className="flex items-center justify-center gap-2">
        <Mark size={40} />
        <BetaPill />
      </div>
      <h2 id={titleId} className="m-0 mt-4 text-2xl font-normal leading-[1.2] tracking-[-0.03em] text-balance">
        {TITLE[step]}
      </h2>
      <p className="mx-auto mb-0 mt-2 max-w-[340px] text-[15px] leading-[1.45] text-muted text-pretty">{sub[step]}</p>

      {banner && step === 'email' && (
        <div role="alert" className="mt-5 rounded-xl bg-bad-bg px-3.5 py-2.5 text-left text-[13.5px] text-bad">
          {banner}
        </div>
      )}

      {step === 'email' && (
        <form noValidate onSubmit={submitEmail} className="mt-7 flex flex-col gap-3 text-left">
          <Outline disabled={busy} onClick={github}>
            <GitHubIcon size={18} />
            Continue with GitHub
          </Outline>
          {GOOGLE_AUTH && (
            <Outline disabled={busy} onClick={() => setBanner("Google sign-in isn't available yet. Use GitHub or your email.")}>
              <GoogleIcon />
              Continue with Google
            </Outline>
          )}
          <div className="my-1.5 flex items-center gap-3 text-[11px] tracking-[.06em] text-ter">
            <div className="h-px flex-1 bg-hair" />
            OR
            <div className="h-px flex-1 bg-hair" />
          </div>
          <PillInput
            label="Email address"
            type="email"
            autoComplete="email"
            autoFocus={!mobile}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              setError(null)
            }}
            error={err('email')}
          />
          <Solid disabled={busy}>Continue</Solid>
        </form>
      )}

      {(step === 'password' || step === 'new') && (
        <form noValidate onSubmit={step === 'password' ? submitPassword : submitNew} className="mt-6 flex flex-col gap-3 text-left">
          <div className="flex h-12 items-center rounded-full bg-tag pl-5 pr-2 text-base">
            <span className="min-w-0 flex-1 truncate">{email}</span>
            <button type="button" onClick={() => go('email')} className="h-[34px] border-0 bg-transparent px-3 text-sm text-accent">
              Edit
            </button>
          </div>
          {step === 'new' && (
            <PillInput
              label="Your name"
              autoComplete="name"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setError(null)
              }}
              error={err('name')}
            />
          )}
          <PillInput
            label="Password"
            type="password"
            autoComplete={step === 'new' ? 'new-password' : 'current-password'}
            autoFocus={!mobile}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              setError(null)
            }}
            error={err('password')}
          />
          {step === 'new' && password && !err('password') && (
            <span className="flex flex-col gap-1.5 px-5">
              <StrengthMeter password={password} />
            </span>
          )}
          {step === 'password' && resetWorks && (
            <button type="button" disabled={busy} onClick={forgot} className="mr-3 self-end border-0 bg-transparent p-0 text-sm text-accent hover:text-accent-h">
              Forgot password?
            </button>
          )}
          <Solid disabled={busy}>{step === 'new' ? 'Create account' : 'Continue'}</Solid>
        </form>
      )}

      {step === 'invite' && (
        <form noValidate onSubmit={submitInvite} className="mt-6 flex flex-col gap-3 text-left">
          <PillInput
            label="GitHub username or email"
            autoComplete="username"
            value={who}
            onChange={(e) => {
              setWho(e.target.value)
              setError(null)
            }}
            error={err('who')}
          />
          <textarea
            rows={3}
            aria-label="What would you use Otto for? (optional)"
            placeholder="What would you use Otto for? (optional)"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="resize-none rounded-[20px] border border-solid border-field bg-transparent px-5 py-3 text-base leading-[1.45] text-text outline-none focus:border-accent focus:shadow-[0_0_0_2px_var(--accent)]"
            style={{ fontFamily: 'inherit' }}
          />
          <Solid disabled={busy}>Request access</Solid>
          <span className="text-center text-sm text-muted">
            Already have access?{' '}
            {page ? (
              <Link to="/login">Log in</Link>
            ) : (
              <button type="button" onClick={() => go('email')} className="border-0 bg-transparent p-0 text-sm text-accent">
                Log in
              </button>
            )}
          </span>
        </form>
      )}

      {step === 'inviteDone' && (
        <div className="mt-5 flex justify-center">
          <span className="flex size-[52px] items-center justify-center rounded-full bg-ok-bg text-ok">
            <Glyph d={IC.check} size={24} width={2.2} />
          </span>
        </div>
      )}

      {(step === 'inviteDone' || step === 'offline' || step === 'inbox') && (
        <div className={cn('mt-6 flex justify-center gap-2.5', mobile ? 'flex-col' : 'flex-row')}>
          {step === 'offline' && (
            <a
              href={`${LANDING_URL}/#demo`}
              className="inline-flex h-12 items-center justify-center rounded-full bg-inv px-6 text-base text-inv-text hover:text-inv-text hover:opacity-[.82]"
            >
              Watch the demo
            </a>
          )}
          {page ? (
            <a
              href={LANDING_URL}
              className="inline-flex h-12 items-center justify-center rounded-full border border-solid border-field px-6 text-base text-text hover:bg-hover hover:text-text"
            >
              Back to Otto
            </a>
          ) : (
            <Outline onClick={step === 'inbox' ? () => go('password') : back} className="px-6">
              {step === 'inbox' ? 'Back to log in' : 'Close'}
            </Outline>
          )}
        </div>
      )}

      {error?.field === 'form' && (
        <p role="alert" className="mb-0 mt-3 text-sm text-bad">
          {error.message}
        </p>
      )}

      {step === 'email' && (
        <p className="mb-0 mt-5 text-[12.5px] leading-normal text-muted">
          By continuing you agree to the <Link to="/legal/terms">Terms</Link> and <Link to="/legal/privacy">Privacy Policy</Link>.
        </p>
      )}
    </div>
  )

  if (page) return card
  return (
    <div
      className="fixed inset-0 z-[100] flex justify-center bg-scrim animate-fade"
      style={{ alignItems: sheet ? 'flex-end' : 'center', padding: sheet ? 0 : 24 }}
    >
      {card}
    </div>
  )
}

/** A 48px pill input; its placeholder is its label. Red, with the message under it, on error. */
export function PillInput({ label, error, ...input }: ComponentProps<'input'> & { label: string; error?: string }) {
  const msg = useId()
  return (
    <>
      <input
        aria-label={label}
        placeholder={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? msg : undefined}
        className={cn(
          'h-12 rounded-full border border-solid bg-transparent px-5 text-base text-text outline-none focus:border-accent focus:shadow-[0_0_0_2px_var(--accent)]',
          error ? 'border-bad' : 'border-field',
        )}
        style={{ fontFamily: 'inherit' }}
        {...input}
      />
      {error && (
        <span id={msg} role="alert" className="-mt-1 ml-5 text-[13px] text-bad">
          {error}
        </span>
      )}
    </>
  )
}

export function Solid({ children, disabled }: { children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="h-12 rounded-full border-0 bg-inv text-base text-inv-text hover:opacity-[.82] disabled:opacity-60"
    >
      {children}
    </button>
  )
}

function Outline({ children, className, ...props }: ComponentProps<'button'>) {
  return (
    <button
      type="button"
      className={cn(
        'relative flex h-12 items-center justify-center rounded-full border border-solid border-field bg-transparent text-base text-text hover:bg-hover disabled:opacity-60 [&>svg]:absolute [&>svg]:left-5',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z" />
      <path fill="#FBBC05" d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z" />
      <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09c.95-2.85 3.6-4.96 6.73-4.96z" />
    </svg>
  )
}
