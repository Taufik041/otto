import { useState, type FormEvent, type ReactNode } from 'react'
import { api, client } from '@/api'
import { messageOf } from '@/api/errors'
import { Lockup, Mark } from '@/components/brand'
import { Outline, PillInput, Solid } from './SignIn'

// the same check as the sign-in dialog's
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

/** What an email sign-up sees instead of the app until it opens its confirmation link: resend
 *  it, fix the address, or sign out. */
export function ConfirmEmailPage({ email }: { email: string }) {
  const [changing, setChanging] = useState(false)
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<{ field: 'email' | 'form'; message: string } | null>(null)

  async function run(field: 'email' | 'form', fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    setSent(null)
    try {
      await fn()
    } catch (e) {
      setError({ field, message: messageOf(e) })
    }
    setBusy(false)
  }

  const resend = () =>
    run('form', async () => {
      await api.resendMine()
      setSent(`Sent another link to ${email}.`)
    })

  function change(e: FormEvent) {
    e.preventDefault()
    const value = next.trim()
    if (!EMAIL.test(value)) return setError({ field: 'email', message: 'Enter a valid email.' })
    return run('email', async () => {
      const user = await api.changeEmail(value)
      setChanging(false)
      setNext('')
      setSent(`Sent a link to ${user.email}.`)
    })
  }

  return (
    <Page>
      <h1 id="confirm-title" className="m-0 mt-4 text-2xl font-normal leading-[1.2] tracking-[-0.03em]">
        Confirm your email
      </h1>
      <p className="mx-auto mb-0 mt-2 max-w-[340px] text-[15px] leading-[1.45] text-muted text-pretty">
        We sent a link to {email}. Open it to start using Otto. It expires in 24 hours.
      </p>
      {changing ? (
        <form noValidate onSubmit={change} className="mt-6 flex flex-col gap-3 text-left">
          <PillInput
            label="New email address"
            type="email"
            autoComplete="email"
            autoFocus
            value={next}
            onChange={(e) => {
              setNext(e.target.value)
              setError(null)
            }}
            error={error?.field === 'email' ? error.message : undefined}
          />
          <Solid disabled={busy}>Send link</Solid>
          <Outline onClick={() => (setChanging(false), setError(null))}>Cancel</Outline>
        </form>
      ) : (
        <div className="mt-6 flex flex-col gap-3">
          <Outline disabled={busy} onClick={resend}>
            Resend
          </Outline>
          <Outline disabled={busy} onClick={() => (setChanging(true), setSent(null), setError(null))}>
            Change email
          </Outline>
        </div>
      )}
      {sent && (
        <p role="status" className="mb-0 mt-3 text-sm text-muted">
          {sent} Check your inbox, and your spam folder too.
        </p>
      )}
      {error?.field === 'form' && (
        <p role="alert" className="mb-0 mt-3 text-sm text-bad">
          {error.message}
        </p>
      )}
      <p className="mb-0 mt-5 text-sm">
        <button type="button" onClick={() => client.logout()} className="border-0 bg-transparent p-0 text-sm text-accent">
          Sign out
        </button>
      </p>
    </Page>
  )
}

/** The confirmation pages' layout: the lockup bar, then a centered card. */
export function Page({ children, labelledBy = 'confirm-title' }: { children: ReactNode; labelledBy?: string }) {
  return (
    <main className="min-h-full bg-bg">
      <div className="flex h-[52px] items-center bg-bg2 px-5 sm:px-8">
        <Lockup height={22} />
      </div>
      <div className="flex justify-center px-4 pb-20 pt-10 sm:pt-[88px]">
        <section
          aria-labelledby={labelledBy}
          className="w-full max-w-[448px] rounded-[20px] bg-card px-6 py-8 text-center shadow-[var(--shadow),0_0_0_1px_var(--hair)] sm:px-10 sm:pb-8 sm:pt-9"
        >
          <div className="flex justify-center">
            <Mark size={40} />
          </div>
          {children}
        </section>
      </div>
    </main>
  )
}
