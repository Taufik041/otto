import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'
import { Glyph, IC } from '@/chat/icons'
import { BetaPill, GitHubIcon, Lockup, Mark } from '@/components/brand'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { cn } from '@/utils/cn'
import { API_URL, APP_URL, CODE_URL, CONTACT_EMAIL, DEMO_BOOKING_URL, GITHUB_URL, LINKEDIN_URL, STATUS_OVERRIDE } from './config'
import { OfflineDialog } from './OfflineDialog'
import { INNER_W } from './replay'
import { Replay } from './Replay'
import { Architecture, Bento, HowItWorks, Marquee, TwoTone } from './Sections'
import { useStatus, type Status } from './status'

const LOGIN = `${APP_URL}/login`
const MENU = 'M4 7h16M4 12h16M4 17h16'

/** "Get started" and "Log in": the app's sign-in while Otto is live; the offline dialog when not. */
function useEntry(status: Status, openOffline: () => void) {
  return (e: MouseEvent) => {
    if (status !== 'offline') return // live, or still asking: the link goes to the app
    e.preventDefault()
    openOffline()
  }
}

function StatusDot({ status }: { status: Status }) {
  const off = status === 'offline'
  return (
    <span
      aria-hidden="true"
      className={cn('size-[7px] shrink-0 rounded-full', !off && status === 'live' && 'animate-[otto-pulse_2.4s_ease-in-out_infinite]')}
      style={{
        background: off ? 'transparent' : status === 'chat' ? 'var(--warn)' : 'var(--accent)',
        boxShadow: off ? 'inset 0 0 0 1.5px var(--ter)' : status === 'chat' ? '0 0 0 3px var(--warn-bg)' : '0 0 0 3px var(--accent-bg)',
        opacity: status === 'checking' ? 0 : 1,
      }}
    />
  )
}

const statusLong = (s: Status) =>
  s === 'offline' ? 'Otto is offline right now' : s === 'chat' ? 'Chat is live · sandboxes are offline right now' : 'Otto is live'
const statusShort = (s: Status) => (s === 'offline' ? 'Offline' : s === 'chat' ? 'Chat only' : s === 'live' ? 'Live' : 'Checking')

/** The nav, footer and offline dialog around a landing page (the page, or its 404). */
export function Shell({ children }: { children: (entry: (e: MouseEvent) => void, mobile: boolean) => ReactNode }) {
  const mobile = useIsMobile()
  const status = useStatus({ apiUrl: API_URL, override: STATUS_OVERRIDE })
  const [offline, setOffline] = useState(false)
  const [menuOpen, setMenu] = useState(false)
  const menu = menuOpen && mobile // the sheet is a phone's; a wider window has the nav
  const entry = useEntry(status, () => {
    setMenu(false)
    setOffline(true)
  })
  const links = [
    { label: 'How it works', href: '/#how' },
    { label: 'Architecture', href: '/#architecture' },
    { label: 'GitHub', href: CODE_URL, external: true },
  ]

  return (
    <div className="min-h-full bg-bg text-text">
      <header className="sticky top-0 z-50 flex h-[52px] items-center gap-6 bg-bg2" style={{ padding: mobile ? '0 20px' : '0 32px' }}>
        <a href="/" aria-label="Otto home" className="flex shrink-0 items-center gap-2">
          <Lockup height={22} />
          <BetaPill />
        </a>
        {!mobile && (
          <nav aria-label="Sections" className="flex items-center gap-0.5">
            {links.map((l) => (
              <a key={l.label} href={l.href} {...(l.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                className="flex h-7 items-center rounded-full px-3 text-sm text-text hover:bg-hover hover:text-text">
                {l.label}
              </a>
            ))}
          </nav>
        )}
        <div className="flex-1" />
        <span
          role="status"
          title={statusLong(status)}
          className={cn('inline-flex h-7 items-center gap-[7px] rounded-full text-[13px] text-muted', mobile ? 'px-1' : 'border border-solid border-line pl-2.5 pr-[11px]')}
        >
          <StatusDot status={status} />
          {mobile ? <span className="sr-only">{statusLong(status)}</span> : <span>{statusShort(status)}</span>}
        </span>
        {!mobile ? (
          <div className="flex items-center gap-2">
            <a href={LOGIN} onClick={entry} className="inline-flex h-8 items-center rounded-full border border-solid border-line px-3.5 text-sm text-text hover:bg-hover hover:text-text">
              Log in
            </a>
            <a href={LOGIN} onClick={entry} className="inline-flex h-8 items-center rounded-full bg-inv px-3.5 text-sm text-inv-text hover:text-inv-text hover:opacity-[.82]">
              Get started
            </a>
          </div>
        ) : (
          <button
            type="button"
            aria-label={menu ? 'Close menu' : 'Menu'}
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
            className="-mr-2 flex size-10 items-center justify-center rounded-full border-0 bg-transparent text-text"
          >
            <Glyph d={menu ? IC.x : MENU} size={20} width={1.7} />
          </button>
        )}
      </header>

      {menu && (
        <div
          role="dialog"
          aria-label="Menu"
          className="fixed inset-x-0 bottom-0 top-[52px] z-[49] flex flex-col bg-[color-mix(in_srgb,var(--bg2)_95%,transparent)] backdrop-blur-[12px] animate-fade"
        >
          <nav aria-label="Sections" className="flex-1 px-5 py-2">
            {links.map((l) => (
              <a key={l.label} href={l.href} onClick={() => setMenu(false)} {...(l.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                className="flex h-14 items-center border-0 border-b border-solid border-hair text-[17px] text-text hover:text-text">
                <span className="flex-1">{l.label}</span>
                <Glyph d="M9.5 6l6 6-6 6" size={14} width={2} className="text-ter" />
              </a>
            ))}
            <div className="flex h-14 items-center gap-2 text-[15px] text-muted">
              <StatusDot status={status} />
              {statusLong(status)}
            </div>
          </nav>
          <div className="flex gap-2.5 px-5 pb-[34px] pt-4">
            <a href={LOGIN} onClick={entry} className="flex h-11 flex-1 items-center justify-center rounded-full border border-solid border-line text-base text-text hover:text-text">
              Log in
            </a>
            <a href={LOGIN} onClick={entry} className="flex h-11 flex-1 items-center justify-center rounded-full bg-inv text-base text-inv-text hover:text-inv-text">
              Get started
            </a>
          </div>
        </div>
      )}

      <main>{children(entry, mobile)}</main>

      <footer className="border-0 border-t border-solid border-hair bg-bg2">
        <div
          className="mx-auto grid max-w-[1200px] gap-x-6 gap-y-9"
          style={{ padding: mobile ? '48px 20px 56px' : '64px 48px 72px', gridTemplateColumns: mobile ? 'repeat(2,minmax(0,1fr))' : '2fr 1fr 1fr 1fr' }}
        >
          <div className="flex flex-col gap-3" style={{ gridColumn: mobile ? '1 / -1' : 'auto' }}>
            <Lockup height={22} />
            <span className="text-sm text-muted">Built by Taufik Khan</span>
            <span className="text-sm text-muted">Otto is in beta. It may be offline at times.</span>
            <span className="mt-2 flex items-center gap-2 text-[13px] text-muted">
              <StatusDot status={status} />
              {status === 'offline' ? 'Offline right now' : status === 'chat' ? 'Chat is live · sandboxes are offline right now' : 'All systems live'}
            </span>
          </div>
          <FootCol title="Product">
            <a href={LOGIN} onClick={entry}>Try Otto</a>
            <a href="/#how">How it works</a>
            <a href="/#architecture">Architecture</a>
          </FootCol>
          <FootCol title="Legal">
            <a href={`${APP_URL}/legal/terms`}>Terms of Service</a>
            <a href={`${APP_URL}/legal/privacy`}>Privacy Policy</a>
            <a href={`${APP_URL}/legal/acceptable-use`}>Acceptable Use</a>
          </FootCol>
          <FootCol title="Connect">
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
            {LINKEDIN_URL && <a href={LINKEDIN_URL} target="_blank" rel="noopener noreferrer">LinkedIn</a>}
            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          </FootCol>
        </div>
      </footer>

      {offline && (
        <OfflineDialog
          mobile={mobile}
          bookingUrl={DEMO_BOOKING_URL}
          onClose={() => setOffline(false)}
          onWatch={() => {
            setOffline(false)
            document.querySelector('#demo')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }}
        />
      )}
    </div>
  )
}

function FootCol({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5 text-sm [&>a]:text-muted [&>a:hover]:text-text">
      <div className="text-text">{title}</div>
      {children}
    </div>
  )
}

// --- the page ------------------------------------------------------------------------------

const FRAGMENTS: [text: string, x: string, y: string, size: number, color: string, opacity: number, seconds: number][] = [
  ['$ pytest -q', '5%', '34%', 13, 'var(--muted)', 0.5, 140],
  ['- return quantity > BULK_THRESHOLD', '62%', '7%', 12.5, 'var(--bad)', 0.4, 180],
  ['+ return quantity >= BULK_THRESHOLD', '67%', '12%', 12.5, 'var(--ok)', 0.45, 160],
  ['9 passed in 0.09s', '84%', '44%', 13, 'var(--ok)', 0.4, 90],
  ['git commit -am "Fix bulk discount threshold"', '2%', '64%', 12, 'var(--muted)', 0.35, 200],
  ['@@ -20,7 +20,7 @@', '46%', '3%', 12, 'var(--muted)', 0.4, 120],
  ['2 failed, 7 passed', '88%', '72%', 12.5, 'var(--bad)', 0.35, 110],
  ['def qualifies_for_bulk(quantity: int) -> bool:', '56%', '93%', 12, 'var(--muted)', 0.35, 150],
  ['$ rg -n qualifies_for_bulk src', '8%', '90%', 12, 'var(--muted)', 0.35, 70],
]
// phones: fewer, placed clear of the headline (the design's own positions)
const PHONE_FRAGMENTS: typeof FRAGMENTS = [
  ['$ pytest -q', '6%', '52%', 12, 'var(--muted)', 0.45, 140],
  ['9 passed in 0.09s', '58%', '54%', 12, 'var(--ok)', 0.4, 90],
  ['+ return quantity >= BULK_THRESHOLD', '4%', '95%', 11.5, 'var(--ok)', 0.4, 160],
  ['2 failed, 7 passed', '60%', '97%', 11.5, 'var(--bad)', 0.35, 110],
]

/** The hero window's width: the column's on desktop; a readable 800px on phones (cropped). */
function useColumnWidth(mobile: boolean) {
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(INNER_W)
  useEffect(() => {
    if (!el || mobile) return
    const measure = () => setWidth(el.clientWidth || INNER_W)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [el, mobile])
  return { setEl, width: mobile ? 800 : width }
}

export function Landing() {
  return (
    <Shell>
      {(entry, mobile) => <Page entry={entry} mobile={mobile} />}
    </Shell>
  )
}

function Page({ entry, mobile }: { entry: (e: MouseEvent) => void; mobile: boolean }) {
  const { setEl: demoRef, width: demoWidth } = useColumnWidth(mobile)
  const pad = mobile ? 'px-5' : 'px-12'
  return (
    <>
      <section className="relative overflow-hidden" style={{ padding: mobile ? '48px 0 40px' : '88px 0 96px' }}>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
          {(mobile ? PHONE_FRAGMENTS : FRAGMENTS).map(([t, x, y, size, color, opacity, s], i) => (
            <span
              key={t}
              className="absolute whitespace-nowrap font-mono"
              style={{ left: x, top: y, fontSize: size, color, opacity, animation: `otto-drift ${s}s linear ${-i * 9}s infinite alternate` }}
            >
              {t}
            </span>
          ))}
        </div>
        <div className={cn('relative mx-auto max-w-[1200px]', pad)}>
          <p className="m-0 mb-4 text-sm text-muted">Free during beta</p>
          <h1 className="m-0 max-w-[760px] font-normal leading-[1.04] tracking-[-0.03em] text-balance" style={{ fontSize: mobile ? 34 : 52 }}>
            <span className="block text-ter">Describe the change.</span>
            <span className="block">Otto opens the pull request.</span>
          </h1>
          <p className="m-0 mt-5 max-w-[46ch] leading-[1.45] text-muted text-pretty" style={{ fontSize: mobile ? 16 : 18 }}>
            An autonomous coding agent that works in its own cloud sandbox, runs your tests, and proposes a PR you approve.
          </p>
          <div className="mt-7 flex flex-wrap gap-2.5">
            <a href={LOGIN} onClick={entry} className="inline-flex h-[42px] items-center rounded-full bg-inv px-5 text-base text-inv-text hover:text-inv-text hover:opacity-[.82]">
              Get started
            </a>
            <a href="#demo" className="inline-flex h-[42px] items-center rounded-full border border-solid border-line px-5 text-base text-text hover:bg-hover hover:text-text">
              Watch it work ↓
            </a>
          </div>

          <div id="demo" ref={demoRef} className="relative scroll-mt-20" style={{ marginTop: mobile ? 44 : 64 }}>
            <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-[55%] h-[150%] w-[130%] -translate-x-1/2 -translate-y-1/2 bg-[radial-gradient(closest-side,var(--glow),transparent)]" />
            <Replay width={demoWidth} />
            {!mobile && <FloatingPr />}
          </div>
        </div>
      </section>

      <Marquee />
      <HowItWorks mobile={mobile} />
      <Bento mobile={mobile} />
      <Architecture mobile={mobile} />

      <section className="text-center" style={{ padding: mobile ? '88px 0 96px' : '160px 0 168px' }}>
        <TwoTone
          first="Stop babysitting small fixes."
          second="Let Otto open the PR."
          size={mobile ? 'text-[40px]' : 'text-[64px]'}
          className="mx-auto max-w-[900px] px-5 !leading-[1.02] text-balance"
        />
        <div className="mt-8 flex flex-wrap justify-center gap-2.5">
          <a href={LOGIN} onClick={entry} className="inline-flex h-[42px] items-center rounded-full bg-inv px-5 text-base text-inv-text hover:text-inv-text hover:opacity-[.82]">
            Get started
          </a>
          <a href={CODE_URL} target="_blank" rel="noopener noreferrer"
            className="inline-flex h-[42px] items-center gap-2 rounded-full border border-solid border-line px-5 text-base text-text hover:bg-hover hover:text-text">
            <GitHubIcon size={16} />
            View on GitHub
          </a>
        </div>
      </section>
    </>
  )
}

/** The blurred PR card over the window's right edge (desktop). */
function FloatingPr() {
  return (
    <div
      aria-hidden="true"
      className="absolute -right-[72px] -top-[150px] w-[292px] rounded-2xl bg-[color-mix(in_srgb,var(--card)_90%,transparent)] px-[18px] py-4 shadow-[0_25px_50px_-12px_rgba(0,0,0,.18),0_0_0_1px_var(--hair)] backdrop-blur-[8px]"
    >
      <div className="flex items-center gap-[7px] text-xs text-muted">
        <Glyph d={IC.pr} size={13} className="text-ok" />
        <span className="font-medium text-ok">PR open</span>
        <span>· Taufik041/otto_test #9</span>
      </div>
      <div className="mt-2 text-[19px] leading-[1.2] tracking-[-0.03em]">Fix bulk discount threshold</div>
      <div className="mt-1.5 font-mono text-[11.5px] text-muted">
        otto/4299fa2c3f → main · <span className="text-ok">+1</span> <span className="text-bad">−1</span>
      </div>
      <div className="mt-3 border-0 border-t border-solid border-hair pt-3 text-[13px] leading-normal text-muted">
        An order of exactly 10 units now gets the bulk discount, matching docs/PRICING.md.
      </div>
      <div className="mt-2.5 text-[13px] font-medium text-ok">✓ 9 tests passed</div>
    </div>
  )
}

/** The landing page's own 404 (404.html). */
export function LandingNotFound() {
  return (
    <Shell>
      {() => (
        <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 py-12 text-center">
          <Mark size={72} className="animate-[otto-once_2.6s_cubic-bezier(.45,0,.2,1)_.5s_1_both]" />
          <div className="mt-7 font-mono text-[13px] text-ter">404</div>
          <h1 className="m-0 mt-2 text-[36px] font-normal leading-[1.06] tracking-[-0.03em] text-balance sm:text-[48px]">
            This page took a wrong turn.
          </h1>
          <p className="m-0 mt-3 text-base text-muted">The link may be old, or the page moved.</p>
          <a href="/" className="mt-7 inline-flex h-[42px] items-center rounded-full bg-inv px-[22px] text-base text-inv-text hover:text-inv-text hover:opacity-[.82]">
            Go home
          </a>
        </div>
      )}
    </Shell>
  )
}
