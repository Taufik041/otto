import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, goToGitHub } from '@/api'
import { messageOf } from '@/api/errors'
import { keys, useGitHub, useRepos } from '@/api/queries'
import type { Unlinked } from '@/api/types'
import { rememberReturn, takeReturn, useMe } from '@/auth/auth'
import { GitHubIcon } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { RepoRow } from '@/pages/OnboardingPage'
import { updatedAgo } from '@/utils/format'
import { Card, Loading, Problem, SectionLabel } from './parts'

/** GitHub: the linked account, the repos Otto can reach, and the App's installations. */
export function GitHubPage() {
  const me = useMe()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const github = useGitHub()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // GitHub's install flow always ends here; go on to the page that started it (onboarding, home)
  useEffect(() => {
    const back = takeReturn()
    if (back && back !== '/settings/github') navigate(back, { replace: true })
    qc.invalidateQueries({ queryKey: keys.github })
    qc.invalidateQueries({ queryKey: keys.repos })
  }, [navigate, qc])

  async function go(get: () => Promise<{ url: string }>) {
    setBusy(true)
    setError(null)
    rememberReturn('/settings/github')
    try {
      await goToGitHub(get)
    } catch (e) {
      setError(messageOf(e))
      setBusy(false)
    }
  }

  if (github.isPending) return <Loading />
  if (github.isError) return <Problem error={github.error} />
  const gh = github.data

  if (!me.github_login && !gh.connected) {
    return (
      <Card className="px-7 py-10 text-center">
        <GitHubIcon size={34} className="mx-auto" />
        <div className="mt-3.5 text-[19px] font-semibold">GitHub isn't connected.</div>
        <p className="mx-auto mb-0 mt-1.5 max-w-[360px] text-[15px] text-muted">
          Connect it so Otto can work on your repos. Otto only sees the repos you choose.
        </p>
        <Button variant="dark" size="none" className="mt-5 h-11 gap-[9px] px-[22px] text-base" disabled={busy} onClick={() => go(() => api.githubUrl('link'))}>
          <GitHubIcon size={17} />
          Connect GitHub
        </Button>
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-bad">{error}</p>}
      </Card>
    )
  }

  return (
    <>
      <Card className="flex items-center gap-3.5 px-5 py-[18px]">
        {gh.avatar_url ? (
          <img src={gh.avatar_url} alt="" className="size-11 shrink-0 rounded-full bg-sel object-cover" />
        ) : (
          <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-inv text-inv-text">
            <GitHubIcon size={22} />
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-semibold">{gh.login ? `@${gh.login}` : 'GitHub'}</span>
          <span className="flex items-center gap-1.5 text-[13.5px] text-muted">
            <span className="size-1.5 rounded-full" style={{ background: gh.connected ? 'var(--ok)' : 'var(--idle)' }} />
            {gh.connected ? 'Connected' : 'Linked. Otto isn’t installed on any repositories yet.'}
          </span>
        </span>
        {!me.github_login && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => go(() => api.githubUrl('link'))}>
            Link account
          </Button>
        )}
      </Card>

      {gh.connected && <Repos />}

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <Button disabled={busy} onClick={() => go(api.installUrl)} className="gap-[7px]">
          {gh.connected ? 'Add or remove repositories' : 'Install on repositories'}
          <ExternalLink size={13} strokeWidth={2} />
        </Button>
      </div>
      {error && <p role="alert" className="-mt-4 mb-0 text-sm text-bad">{error}</p>}

      {gh.installations.length > 0 && <Installations installations={gh.installations} />}
    </>
  )
}

function Repos() {
  const repos = useRepos()
  return (
    <div>
      <SectionLabel>Repositories Otto can access</SectionLabel>
      {repos.isPending ? (
        <Loading />
      ) : repos.isError ? (
        <Problem error={repos.error} />
      ) : repos.data.length === 0 ? (
        <Card className="px-5 py-4 text-[15px] text-muted">Otto can't see any repositories yet.</Card>
      ) : (
        <Card className="overflow-hidden">
          {repos.data.map((r, i) => (
            <RepoRow
              key={r.full_name}
              full={r.full_name}
              first={i === 0}
              priv={r.private}
              pad="px-5"
              meta={`${r.private ? 'Private' : 'Public'} · ${updatedAgo(r.updated_at).replace(/^updated /, '')}`}
            />
          ))}
        </Card>
      )}
    </div>
  )
}

function Installations({ installations }: { installations: { id: number; account_login: string }[] }) {
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState<{ id: number; account_login: string } | null>(null)
  const [done, setDone] = useState<(Unlinked & { account_login: string }) | null>(null)
  const unlink = useMutation({
    mutationFn: (id: number) => api.unlinkInstallation(id),
    onSuccess: (res) => {
      setDone({ ...res, account_login: confirm?.account_login ?? '' })
      setConfirm(null)
      qc.invalidateQueries({ queryKey: keys.github })
      qc.invalidateQueries({ queryKey: keys.repos })
    },
  })
  return (
    <div>
      <SectionLabel>Installations</SectionLabel>
      <Card className="overflow-hidden">
        {installations.map((inst, i) => (
          <div
            key={inst.id}
            className="flex items-center gap-3 px-5 py-3.5"
            style={{ borderTop: i ? '1px solid var(--hair)' : 'none' }}
          >
            <GitHubIcon size={16} className="text-muted" />
            <span className="min-w-0 flex-1 truncate text-[15px]">{inst.account_login}</span>
            <button
              type="button"
              onClick={() => setConfirm(inst)}
              className="border-0 bg-transparent p-0 text-[15px] text-bad"
            >
              Disconnect
            </button>
          </div>
        ))}
      </Card>
      {done && (
        <p role="status" className="mx-1 mb-0 mt-2.5 text-sm text-muted">
          Disconnected {done.account_login}. The App stays installed on GitHub until you{' '}
          <a href={done.uninstall_url} target="_blank" rel="noopener noreferrer">
            uninstall it there ›
          </a>
        </p>
      )}
      <Dialog
        open={confirm !== null}
        onOpenChange={(o) => {
          if (!o) {
            setConfirm(null)
            unlink.reset()
          }
        }}
      >
        {confirm && (
          <DialogContent>
            <DialogTitle>Disconnect {confirm.account_login}?</DialogTitle>
            <DialogDescription>Otto stops seeing its repositories. You can connect it again any time.</DialogDescription>
            {unlink.isError && <p role="alert" className="mb-0 mt-3 text-sm text-bad">{messageOf(unlink.error)}</p>}
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              </DialogClose>
              <Button variant="dangerSolid" size="sm" disabled={unlink.isPending} onClick={() => unlink.mutate(confirm.id)}>
                Disconnect
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  )
}
