import { Check, Globe, Lock } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { api, goToGitHub } from '@/api'
import { messageOf } from '@/api/errors'
import { useGitHub, useRepos } from '@/api/queries'
import { markOnboarded, rememberReturn, useMe } from '@/auth/auth'
import { GitHubIcon, Mark } from '@/components/brand'
import { Button } from '@/components/ui/button'
import type { Repo } from '@/api/types'
import { ownerOf, shortName } from '@/utils/mention'

/**
 * First run: connect GitHub, then pick the repos Otto may use. Each step can be skipped.
 *
 * 1. No GitHub account linked: "Connect GitHub" links it (POST /auth/github/url, mode "link");
 *    GitHub sends the browser back through /auth/callback, which returns here.
 * 2. Linked, but the App isn't installed anywhere: "Install on repositories" (POST
 *    /github/install-url); GitHub sends the browser to /settings/github, which returns here.
 * 3. Installed: "Connected. N repositories available." and the list.
 */
export function OnboardingPage() {
  const me = useMe()
  const navigate = useNavigate()
  const github = useGitHub()
  const installed = github.data?.connected === true
  const repos = useRepos()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finish = () => {
    markOnboarded(me.id)
    navigate('/', { replace: true })
  }

  async function go(get: () => Promise<{ url: string }>) {
    setBusy(true)
    setError(null)
    rememberReturn('/welcome')
    try {
      await goToGitHub(get)
    } catch (e) {
      setError(messageOf(e))
      setBusy(false)
    }
  }

  const step = github.isPending ? null : installed ? 'done' : me.github_login ? 'install' : 'link'

  return (
    <main className="flex min-h-full flex-col items-center overflow-y-auto bg-bg px-4 py-6 sm:px-6 sm:py-12">
      <div className="flex-[1_1_auto]" />
      {step && (
        <div className="w-full max-w-[520px] text-center animate-[otto-pop_.45s_ease-out_both]">
          {step === 'done' ? (
            <Connected repos={repos.data} loading={repos.isPending} onStart={finish} />
          ) : (
            <>
              <Mark size={64} className="mx-auto" />
              <h1 className="mx-0 mb-0 mt-7 text-[30px] font-normal leading-[1.1] tracking-[-0.03em] text-balance sm:text-[44px]">
                {step === 'link' ? 'Connect GitHub so Otto can work on your repos.' : 'Choose the repos Otto can work on.'}
              </h1>
              <p className="mx-auto mb-0 mt-4 max-w-[420px] text-[17px] leading-normal text-muted">
                Otto only sees the repos you choose.
              </p>
              <div className="mt-9 flex flex-col items-center gap-4">
                {step === 'link' ? (
                  <Button variant="primary" size="xl" className="gap-2.5" disabled={busy} onClick={() => go(() => api.githubUrl('link'))}>
                    <GitHubIcon size={19} />
                    Connect GitHub
                  </Button>
                ) : (
                  <Button variant="primary" size="xl" className="gap-2.5" disabled={busy} onClick={() => go(api.installUrl)}>
                    <GitHubIcon size={19} />
                    Install on repositories
                  </Button>
                )}
                {error && (
                  <p role="alert" className="m-0 text-sm text-bad">
                    {error}
                  </p>
                )}
                <a
                  href="/"
                  className="text-[15px]"
                  onClick={(e) => {
                    e.preventDefault()
                    finish()
                  }}
                >
                  Skip for now
                </a>
              </div>
            </>
          )}
        </div>
      )}
      <div className="flex-[1.2_1_auto]" />
    </main>
  )
}

function Connected({ repos, loading, onStart }: { repos?: Repo[]; loading: boolean; onStart: () => void }) {
  const list = repos ?? []
  const n = list.length
  return (
    <>
      <span className="mx-auto flex size-16 items-center justify-center rounded-full bg-ok-bg text-ok">
        <Check size={30} strokeWidth={2.2} />
      </span>
      <h1 className="mx-0 mb-0 mt-7 text-[30px] font-normal leading-[1.1] tracking-[-0.03em] sm:text-[44px]">
        {loading ? 'Connected.' : `Connected. ${n} ${n === 1 ? 'repository' : 'repositories'} available.`}
      </h1>
      {n > 0 && (
        <div className="mx-auto mt-8 max-w-[420px] overflow-hidden rounded-[18px] border border-solid border-line bg-card text-left">
          {list.map((r, i) => (
            <RepoRow key={r.full_name} full={r.full_name} first={i === 0} priv={r.private} meta={r.private ? 'Private' : 'Public'} />
          ))}
        </div>
      )}
      <Button size="xl" className="mt-8 px-[30px]" onClick={onStart}>
        Start a chat
      </Button>
    </>
  )
}

/** One row of the design's repo list (onboarding and Settings › GitHub). */
export function RepoRow({
  full,
  first,
  priv,
  meta,
  pad = 'px-[18px]',
}: {
  full: string
  first: boolean
  priv?: boolean
  meta?: string
  pad?: string
}) {
  const Icon = priv === false ? Globe : Lock
  return (
    <div className={`flex items-center gap-3 py-3.5 ${pad}`} style={{ borderTop: first ? 'none' : '1px solid var(--hair)' }}>
      {priv !== undefined && <Icon size={16} strokeWidth={1.6} className="shrink-0 text-muted" />}
      <span className="min-w-0 flex-1 truncate text-[15px]">
        <span className="text-muted">{ownerOf(full)}/</span>
        {shortName(full)}
      </span>
      {meta && <span className="shrink-0 text-[12.5px] text-muted">{meta}</span>}
    </div>
  )
}
