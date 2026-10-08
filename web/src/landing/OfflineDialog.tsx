import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Mark } from '@/components/brand'
import { cn } from '@/utils/cn'
import { CONTACT_EMAIL } from './config'

export const DEFAULT_MESSAGE = "Hi Taufik, I'd like to try Otto. Could you bring it up?"
const MAX_MESSAGE = 1000
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
type Stage = 'intro' | 'form' | 'sent' | 'limited' | 'fallback'

/** A mailto: carrying what the form would have sent (when /api/wake can't send it). */
export const mailto = (email: string, message: string) =>
  `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Bring Otto back up')}&body=${encodeURIComponent(
    `${message || DEFAULT_MESSAGE}${email ? `\n\nReply to: ${email}` : ''}`,
  )}`

/**
 * "Otto is offline right now." Get started and Log in open it while the API is unreachable. It
 * asks Taufik to bring Otto up (POST /api/wake, a Vercel function that works while the API is
 * down), or books a live demo. If the function can't send, the visitor gets a mailto: instead.
 */
export function OfflineDialog({ mobile, bookingUrl, onClose, onWatch }: {
  mobile: boolean
  /** VITE_DEMO_BOOKING_URL; the button is hidden without it */
  bookingUrl: string | null
  onClose: () => void
  /** "Watch the demo": close, and go to the hero's replay */
  onWatch: () => void
}) {
  const [stage, setStage] = useState<Stage>('intro')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState(DEFAULT_MESSAGE)
  const [website, setWebsite] = useState('') // the honeypot: people never see it
  const [error, setError] = useState<{ field: 'email' | 'message' | 'form'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const openedAt = useRef(0)
  const first = useRef<HTMLButtonElement | HTMLInputElement | null>(null)

  useEffect(() => {
    first.current?.focus()
  }, [stage])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function openForm() {
    openedAt.current = Date.now()
    setStage('form')
  }

  async function send(e: FormEvent) {
    e.preventDefault()
    const value = email.trim()
    if (!EMAIL.test(value)) return setError({ field: 'email', text: 'Enter a valid email.' })
    if (message.length > MAX_MESSAGE) return setError({ field: 'message', text: `Keep it under ${MAX_MESSAGE} characters.` })
    setError(null)
    setBusy(true)
    try {
      const res = await fetch('/api/wake', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: value, message, page: window.location.pathname, openedAt: openedAt.current, website }),
      })
      const body = (await res.json().catch(() => ({}))) as { error?: string }
      if (res.ok) return setStage('sent')
      if (res.status === 429) return setStage('limited')
      if (body.error === 'invalid_email') return setError({ field: 'email', text: 'Enter a valid email.' })
      if (body.error === 'invalid_message') return setError({ field: 'message', text: `Keep it under ${MAX_MESSAGE} characters.` })
      if (body.error === 'too_fast') return setError({ field: 'form', text: 'Give it a few seconds, then send again.' })
      setStage('fallback') // 503 (email isn't set up), 502, anything else
    } catch {
      setStage('fallback') // offline, or the function is down
    } finally {
      setBusy(false)
    }
  }

  const title = stage === 'sent' ? 'Sent.' : stage === 'form' ? 'Bring Otto back up' : 'Otto is offline right now.'
  return (
    <div onClick={onClose} className="fixed inset-0 z-[100] flex justify-center bg-scrim animate-fade" style={{ alignItems: mobile ? 'flex-end' : 'center', padding: mobile ? 0 : 24 }}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="offline-title"
        onClick={(e) => e.stopPropagation()}
        className="relative w-full bg-card text-center shadow-pop"
        style={{
          maxWidth: mobile ? 'none' : 448,
          borderRadius: mobile ? '24px 24px 0 0' : 20,
          padding: mobile ? '30px 24px 34px' : '36px 40px 32px',
          animation: mobile ? 'otto-sheet .35s cubic-bezier(.2,.8,.2,1) both' : 'otto-pop .3s ease-out both',
        }}
      >
        {mobile && <div aria-hidden="true" className="mx-auto -mt-3.5 mb-[18px] h-[5px] w-9 rounded-full bg-line" />}
        <div className="flex justify-center">
          <Mark size={40} />
        </div>
        <h2 id="offline-title" className="m-0 mt-4 text-2xl font-normal leading-[1.2] tracking-[-0.03em]">
          {title}
        </h2>

        {stage === 'intro' && (
          <>
            <p className="mx-auto mb-0 mt-2 max-w-[360px] text-[15px] leading-[1.45] text-muted text-pretty">
              Otto is a free beta that runs on Taufik's own hardware, so it sleeps when he's away. Ask him to bring it up, or
              book a time and he'll show it to you live.
            </p>
            <div className={cn('mt-6 flex justify-center gap-2.5', mobile ? 'flex-col' : 'flex-row')}>
              <Pill solid onClick={openForm} ref={(el) => void (first.current = el)}>
                Bring it back up
              </Pill>
              {bookingUrl && (
                <a href={bookingUrl} target="_blank" rel="noopener noreferrer" className={PILL_OUTLINE}>
                  Book a live demo
                </a>
              )}
            </div>
            <Links onWatch={onWatch} onClose={onClose} />
          </>
        )}

        {stage === 'form' && (
          <form noValidate onSubmit={send} className="mt-6 flex flex-col gap-3 text-left">
            <input
              ref={(el) => void (first.current = el)}
              type="email"
              aria-label="Your email"
              placeholder="Your email"
              autoComplete="email"
              required
              value={email}
              aria-invalid={error?.field === 'email' || undefined}
              onChange={(e) => {
                setEmail(e.target.value)
                setError(null)
              }}
              className={cn(FIELD, 'h-12 rounded-full', error?.field === 'email' ? 'border-bad' : 'border-field')}
            />
            {error?.field === 'email' && <Problem>{error.text}</Problem>}
            <textarea
              aria-label="Message"
              rows={4}
              maxLength={MAX_MESSAGE}
              value={message}
              onChange={(e) => {
                setMessage(e.target.value)
                setError(null)
              }}
              className={cn(FIELD, 'resize-none rounded-[20px] py-3 leading-[1.45]', error?.field === 'message' ? 'border-bad' : 'border-field')}
            />
            {error?.field === 'message' && <Problem>{error.text}</Problem>}
            {/* the honeypot: hidden from people and screen readers; a bot that fills it is ignored */}
            <input
              type="text"
              name="website"
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              className="absolute -left-[10000px] h-px w-px opacity-0"
            />
            <button type="submit" disabled={busy} className="h-12 rounded-full border-0 bg-inv text-base text-inv-text hover:opacity-[.82] disabled:opacity-60">
              {busy ? 'Sending…' : 'Send'}
            </button>
            {error?.field === 'form' && <Problem center>{error.text}</Problem>}
            <Links onWatch={onWatch} onClose={onClose} />
          </form>
        )}

        {stage === 'sent' && (
          <>
            <p role="status" className="mx-auto mb-0 mt-2 max-w-[360px] text-[15px] leading-[1.45] text-muted">
              Taufik will reply to you at {email.trim()}.
            </p>
            <Links onWatch={onWatch} onClose={onClose} />
          </>
        )}

        {stage === 'limited' && (
          <>
            <p role="alert" className="mx-auto mb-0 mt-2 max-w-[360px] text-[15px] leading-[1.45] text-muted">
              That's a few requests from here already. Try again later, or{' '}
              <a href={mailto(email.trim(), message)}>email {CONTACT_EMAIL}</a>.
            </p>
            <Links onWatch={onWatch} onClose={onClose} />
          </>
        )}

        {stage === 'fallback' && (
          <>
            <p className="mx-auto mb-0 mt-2 max-w-[360px] text-[15px] leading-[1.45] text-muted">
              That didn't go through from here. Send it by email instead:
            </p>
            <div className="mt-6 flex justify-center">
              <a ref={(el) => void (first.current = el as unknown as HTMLButtonElement)} href={mailto(email.trim(), message)} className={PILL_SOLID}>
                Email {CONTACT_EMAIL}
              </a>
            </div>
            <Links onWatch={onWatch} onClose={onClose} />
          </>
        )}
      </div>
    </div>
  )
}

const FIELD = 'border border-solid bg-transparent px-5 text-base text-text outline-none focus:border-accent focus:shadow-[0_0_0_2px_var(--accent)] [font-family:inherit]'
const PILL_SOLID = 'inline-flex h-12 items-center justify-center rounded-full border-0 bg-inv px-6 text-base text-inv-text hover:text-inv-text hover:opacity-[.82]'
const PILL_OUTLINE = 'inline-flex h-12 items-center justify-center rounded-full border border-solid border-field bg-transparent px-6 text-base text-text hover:bg-hover hover:text-text'

function Pill({ solid, children, onClick, ref }: { solid?: boolean; children: ReactNode; onClick: () => void; ref?: (el: HTMLButtonElement | null) => void }) {
  return (
    <button ref={ref} type="button" onClick={onClick} className={solid ? PILL_SOLID : PILL_OUTLINE}>
      {children}
    </button>
  )
}

function Problem({ children, center }: { children: ReactNode; center?: boolean }) {
  return (
    <span role="alert" className={cn('-mt-1 text-[13px] text-bad', center ? 'text-center' : 'ml-5')}>
      {children}
    </span>
  )
}

/** "Watch the demo · Close" as quiet text links. */
function Links({ onWatch, onClose }: { onWatch: () => void; onClose: () => void }) {
  return (
    <div className="mt-5 flex justify-center gap-5 text-sm">
      <a
        href="#demo"
        onClick={(e) => {
          e.preventDefault()
          onWatch()
        }}
      >
        Watch the demo
      </a>
      <button type="button" onClick={onClose} className="border-0 bg-transparent p-0 text-sm text-accent hover:text-accent-h">
        Close
      </button>
    </div>
  )
}
