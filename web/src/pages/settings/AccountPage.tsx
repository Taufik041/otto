import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Mail } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, client } from '@/api'
import { ApiError, messageOf } from '@/api/errors'
import { useMe } from '@/auth/auth'
import { Avatar } from '@/components/Avatar'
import { GitHubIcon } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { StrengthMeter } from '@/pages/auth/StrengthMeter'
import { MIN_PASSWORD } from '@/utils/password'
import { Card, Row } from './parts'

export function AccountPage() {
  const me = useMe()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [pwOpen, setPwOpen] = useState(false)
  const [pwChanged, setPwChanged] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const signOut = async (all: boolean) => {
    try {
      if (all) await client.logoutAll()
      else await client.logout()
    } catch {
      await client.logout() // logout-all failed (offline): at least sign this device out
    }
    qc.clear()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <div className="flex items-center gap-4">
        <Avatar name={me.name} email={me.email} url={me.avatar_url} size={64} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[19px] font-normal tracking-[-0.03em]">{me.name}</span>
          {me.email && <span className="block truncate text-[15px] text-muted">{me.email}</span>}
        </span>
      </div>

      <Card className="overflow-hidden">
        <NameRow />
        <Row>
          <span className="flex-1 text-[15px]">Password</span>
          {me.has_password ? (
            <Button variant="outline" size="sm" onClick={() => setPwOpen(true)}>
              Change password
            </Button>
          ) : (
            <span className="text-sm text-muted">Signs in with GitHub</span>
          )}
        </Row>
        <Row>
          <GitHubIcon size={18} />
          <span className="flex-1 text-[15px]">GitHub</span>
          {me.github_login ? (
            <span className="text-sm text-muted">@{me.github_login}</span>
          ) : (
            <Link to="/settings/github" className="text-sm">
              Connect
            </Link>
          )}
        </Row>
        {me.email && (
          <Row>
            <Mail size={18} strokeWidth={1.6} className="text-muted" />
            <span className="flex-1 text-[15px]">Email</span>
            <span className="min-w-0 truncate text-sm text-muted">{me.email}</span>
          </Row>
        )}
      </Card>
      {pwChanged && (
        <p role="status" className="-mt-4 mb-0 text-sm text-ok">
          Password changed. Your other devices are signed out.
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <Button variant="outline" size="none" className="h-[38px] px-[18px] text-[15px]" onClick={() => signOut(false)}>
          Sign out
        </Button>
        <Button variant="outline" size="none" className="h-[38px] px-[18px] text-[15px]" onClick={() => signOut(true)}>
          Sign out of all devices
        </Button>
      </div>

      <Card className="px-5 py-[18px]">
        <div className="text-[15px] font-medium text-bad">Delete account</div>
        <div className="mt-1 text-sm text-muted">This deletes your chats and disconnects GitHub. It can't be undone.</div>
        <Button variant="danger" size="none" className="mt-3.5 h-9 px-4 text-sm" onClick={() => setDeleteOpen(true)}>
          Delete account
        </Button>
      </Card>

      <ChangePassword
        open={pwOpen}
        onOpenChange={setPwOpen}
        onDone={() => {
          setPwOpen(false)
          setPwChanged(true)
        }}
      />
      <DeleteAccount open={deleteOpen} onOpenChange={setDeleteOpen} />
    </>
  )
}

function NameRow() {
  const me = useMe()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(me.name)
  const save = useMutation({
    mutationFn: (n: string) => api.updateMe({ name: n }),
    onSuccess: (user) => {
      client.setUser(user)
      setEditing(false)
    },
  })
  if (!editing) {
    return (
      <Row first>
        <span className="flex-1 text-[15px]">Name</span>
        <span className="min-w-0 truncate text-sm text-muted">{me.name}</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setName(me.name)
            setEditing(true)
          }}
        >
          Edit
        </Button>
      </Row>
    )
  }
  return (
    <form
      className="flex flex-wrap items-end gap-3 px-5 py-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) save.mutate(name.trim())
      }}
    >
      <Field
        label="Name"
        autoFocus
        className="min-w-[200px] flex-1"
        value={name}
        maxLength={100}
        onChange={(e) => setName(e.target.value)}
        error={save.isError ? messageOf(save.error) : undefined}
      />
      <div className="flex gap-2 pb-1.5">
        <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={!name.trim() || save.isPending}>
          Save
        </Button>
      </div>
    </form>
  )
}

function ChangePassword({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone: () => void
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [wrong, setWrong] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setWrong(false)
    setError(null)
    if (next.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters.`)
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next) // other devices are signed out; this one gets new tokens
      setCurrent('')
      setNext('')
      onDone()
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setWrong(true)
      else setError(messageOf(err))
    }
    setBusy(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Change password</DialogTitle>
        <DialogDescription>Your other devices will be signed out.</DialogDescription>
        <form className="mt-5 flex flex-col gap-3.5" onSubmit={submit} noValidate>
          <Field
            label="Current password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => {
              setCurrent(e.target.value)
              setWrong(false)
            }}
            error={wrong ? "That password isn't right." : undefined}
          />
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => {
              setNext(e.target.value)
              setError(null)
            }}
            error={error ?? undefined}
            note={next ? <span className="flex flex-col gap-1.5"><StrengthMeter password={next} /></span> : undefined}
          />
          <DialogFooter className="mt-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" size="sm" disabled={busy || !current || !next}>
              Change password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteAccount({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const del = useMutation({
    mutationFn: api.deleteMe,
    onSuccess: async () => {
      await client.logout()
      qc.clear()
      navigate('/login', { replace: true })
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Delete your account?</DialogTitle>
        <DialogDescription>
          This deletes your chats and disconnects GitHub. It can't be undone.
        </DialogDescription>
        {del.isError && (
          <p role="alert" className="mb-0 mt-3 text-sm text-bad">
            {messageOf(del.error)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm">
              Cancel
            </Button>
          </DialogClose>
          <Button variant="dangerSolid" size="sm" disabled={del.isPending} onClick={() => del.mutate()}>
            Delete account
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
