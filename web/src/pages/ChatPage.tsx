import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, Ellipsis, Pencil, Square, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { useParams } from 'react-router'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { keys, useModels, useSession } from '@/api/queries'
import { Glyph, IC } from '@/chat/icons'
import type { Step } from '@/chat/reduce'
import { Thread } from '@/chat/Thread'
import { useSessionView } from '@/chat/useSessionView'
import { Workspace, type WorkspaceState } from '@/chat/Workspace'
import { Composer, type ComposerHandle } from '@/composer/Composer'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { DeleteChatDialog } from '@/shell/DeleteChatDialog'
import { useShell } from '@/shell/AppShell'
import { TopBar } from '@/shell/TopBar'

const STICK = 80 // px from the bottom that still counts as "following along"

/** A chat: the conversation with Otto's work in it, the composer, and the workspace panel. */
export function ChatPage() {
  const { id = '' } = useParams()
  return <Chat key={id} id={id} />
}

function Chat({ id }: { id: string }) {
  const { mobile } = useShell()
  const session = useSession(id)
  const models = useModels()
  const { view, connection } = useSessionView(id)
  const composer = useRef<ComposerHandle>(null)
  const [deleting, setDeleting] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [ws, setWs] = useState<WorkspaceState & { open: boolean; step: string | null }>({
    open: false,
    tab: 'changes',
    path: null,
    entry: null,
    step: null,
  })
  const [panelPct, setPanelPct] = useState(45)
  const row = useRef<HTMLDivElement>(null)

  // the follow-up just sent shows until its own message arrives
  const userCount = view.items.filter((i) => i.kind === 'user' && i.text !== null).length
  const [sent, setSent] = useState<{ text: string; repo: string | null; after: number } | null>(null)
  useEffect(() => {
    if (sent && userCount > sent.after) setSent(null)
  }, [sent, userCount])

  const s = session.data
  const repo = view.repo ?? s?.repo ?? null
  const model = view.model ?? s?.model ?? null
  const modelLabel = models.data?.models.find((m) => m.id === model)?.label ?? model
  const branch = s?.work_branch ?? null
  const title = s?.title ?? view.task ?? ''

  // follow along at the bottom unless the reader scrolled up; then offer a way back
  const scroller = useRef<HTMLDivElement>(null)
  const [stuck, setStuck] = useState(true)
  const [unseen, setUnseen] = useState(false)
  const toBottom = useCallback((smooth: boolean) => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }, [])
  useLayoutEffect(() => {
    if (stuck) toBottom(false)
    else setUnseen(true)
  }, [view.items, sent, stuck, toBottom])
  const onScroll = () => {
    const el = scroller.current!
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < STICK
    setStuck(atBottom)
    if (atBottom) setUnseen(false)
  }

  const openStep = (step: Step) =>
    setWs((w) =>
      step.target
        ? { open: true, tab: step.target.tab, path: step.target.tab === 'changes' ? step.target.path : w.path, entry: step.target.entry, step: step.id }
        : { ...w, open: true, step: step.id },
    )

  const startDrag = (e: ReactMouseEvent) => {
    e.preventDefault()
    const r = row.current?.getBoundingClientRect()
    if (!r) return
    const move = (ev: MouseEvent) => setPanelPct(Math.max(30, Math.min(70, ((r.right - ev.clientX) / r.width) * 100)))
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const stop = useMutation({ mutationFn: () => api.stop(id) })
  const panelOpen = ws.open && repo !== null

  return (
    <div ref={row} className="relative flex h-full min-h-0 min-w-0 flex-1">
      <div className="relative flex min-w-0 flex-1 flex-col bg-bg">
        <TopBar title={title} repo={repo} model={modelLabel}>
          {repo && !mobile && (
            <button
              type="button"
              title="Workspace"
              aria-label="Workspace"
              aria-pressed={panelOpen}
              onClick={() => setWs((w) => ({ ...w, open: !w.open }))}
              className="flex size-9 shrink-0 items-center justify-center rounded-[10px] border-0 text-text hover:bg-sel"
              style={{ background: panelOpen ? 'var(--sel)' : 'transparent' }}
            >
              <Glyph d={IC.panel} size={18} width={1.6} />
            </button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title="More"
                aria-label="More"
                className="flex size-9 shrink-0 items-center justify-center rounded-[10px] border-0 bg-transparent text-text hover:bg-sel data-[state=open]:bg-sel"
              >
                <Ellipsis size={20} strokeWidth={2.2} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[200px]">
              <DropdownMenuItem onSelect={() => setRenaming(true)}>
                <Pencil strokeWidth={1.6} />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!view.live} onSelect={() => stop.mutate()}>
                <Square strokeWidth={0} fill="currentColor" />
                Stop
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="danger" onSelect={() => setDeleting(true)}>
                <Trash2 />
                Delete chat
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </TopBar>

        {connection === 'reconnecting' && (
          <div role="status" className="absolute inset-x-0 top-[60px] z-10 flex justify-center animate-fade">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-nav px-3 py-1 text-xs text-muted shadow-pop backdrop-blur-[20px]">
              <Glyph d={IC.spin} size={12} width={2} className="animate-spin-slow" />
              Reconnecting…
            </span>
          </div>
        )}

        <div ref={scroller} onScroll={onScroll} className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-[52px]">
          <div
            className="mx-auto flex w-full flex-col"
            style={{ maxWidth: mobile ? '100%' : 760, padding: mobile ? '20px 16px 12px' : '36px 32px 24px' }}
          >
            {session.isError && <p className="text-center text-sm text-muted">{messageOf(session.error)}</p>}
            <Thread
              sessionId={id}
              items={view.items}
              live={view.live}
              repo={repo}
              branch={branch}
              sent={sent}
              selectedStep={panelOpen ? ws.step : null}
              onOpenStep={openStep}
              onOpenWorkspace={() => setWs((w) => ({ ...w, open: true }))}
              onSeeChanges={(path) => setWs({ open: true, tab: 'changes', path, entry: null, step: null })}
              onMention={() => composer.current?.mention()}
            />
          </div>
        </div>

        {unseen && !stuck && (
          <div className="pointer-events-none absolute inset-x-0 z-10 flex justify-center" style={{ bottom: mobile ? 150 : 140 }}>
            <button
              type="button"
              onClick={() => toBottom(true)}
              className="pointer-events-auto inline-flex h-8 items-center gap-1.5 rounded-full border border-solid border-line bg-card px-3.5 text-[13px] text-text shadow-pop animate-pop"
            >
              <ArrowDown size={14} strokeWidth={2} />
              Jump to latest
            </button>
          </div>
        )}

        <Composer
          handle={composer}
          mobile={mobile}
          hero={false}
          reply={{
            sessionId: id,
            live: view.live,
            model,
            repo,
            onSent: (text, r) => {
              setSent({ text, repo: r, after: userCount })
              setStuck(true)
            },
          }}
        />
      </div>

      {panelOpen && (
        <div className="relative min-w-0" style={mobile ? undefined : { flex: `0 0 ${panelPct}%` }}>
          {!mobile && (
            <div
              title="Drag to resize"
              onMouseDown={startDrag}
              className="absolute inset-y-0 -left-1 z-[5] w-2 cursor-col-resize"
            />
          )}
          <Workspace
            repo={repo!}
            branch={branch}
            files={view.files}
            terminal={view.terminal}
            state={ws}
            onState={(st) => setWs((w) => ({ ...w, ...st }))}
            onClose={() => setWs((w) => ({ ...w, open: false }))}
            mobile={mobile}
          />
        </div>
      )}

      <DeleteChatDialog chat={deleting && s ? s : null} onOpenChange={setDeleting} />
      {s && <RenameDialog key={String(renaming)} id={id} title={s.title} open={renaming} onOpenChange={setRenaming} />}
    </div>
  )
}

function RenameDialog({ id, title, open, onOpenChange }: { id: string; title: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [value, setValue] = useState(title)
  const qc = useQueryClient()
  const rename = useMutation({
    mutationFn: (t: string) => api.rename(id, t),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.sessions }) // the list and this chat (['sessions', id])
      onOpenChange(false)
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (value.trim()) rename.mutate(value.trim())
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Rename chat</DialogTitle>
        <form onSubmit={submit} className="mt-4">
          <Field label="Name" autoFocus maxLength={200} value={value} onChange={(e) => setValue(e.target.value)} error={rename.isError ? messageOf(rename.error) : undefined} />
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" size="sm" disabled={!value.trim() || rename.isPending}>
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
