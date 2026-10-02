import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, AtSign, ChevronDown, Square, X } from 'lucide-react'
import { useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type Ref } from 'react'
import { useNavigate } from 'react-router'
import { api, goToGitHub } from '@/api'
import { messageOf } from '@/api/errors'
import { keys, useModels, useRepos } from '@/api/queries'
import type { Repo } from '@/api/types'
import { rememberReturn, useMe } from '@/auth/auth'
import { RepoIcon } from '@/components/icons'
import { cn } from '@/utils/cn'
import { activeMention, extractRepo, filterRepos, removeMention, shortName, type ActiveMention } from '@/utils/mention'
import { MentionMenu, NoRepos } from './MentionMenu'
import { ModelMenu } from './ModelMenu'
import { initialModel } from './models'
import { ComposerPopover } from './Popover'
import { sendProblem, type SendProblem } from './sendErrors'
import { SendProblemCard } from './SendProblemCard'

export const DISCLAIMER = 'Otto uses AI models and can make mistakes.'
export const REPO_DISCLAIMER =
  'Otto works in a sandbox and opens a pull request. Otto uses AI models and can make mistakes, so review changes before merging.'

export type Suggestion = { text: string; repo: Repo | null; mentionAtEnd?: boolean }

/** Replying in an existing chat: its model is fixed, and while Otto works Send is Stop. */
export type Reply = {
  sessionId: string
  live: boolean
  model: string | null
  repo: string | null
  /** the follow-up went: the chat shows it until its own event arrives */
  onSent: (text: string, repo: string | null) => void
}

export type ComposerHandle = { mention: () => void }

/**
 * The composer: a growing textarea with an inline repo chip, the model picker, the @ repo picker
 * and Send. A new chat (POST /sessions) opens it; a reply (POST /sessions/{id}/messages) stays.
 */
export function Composer({
  mobile,
  hero,
  suggestions = [],
  reply,
  handle,
}: {
  mobile: boolean
  /** the empty state: a taller box, menus open below it, suggestions under (desktop) or above (phones) */
  hero: boolean
  suggestions?: Suggestion[]
  reply?: Reply
  handle?: Ref<ComposerHandle>
}) {
  const me = useMe()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const models = useModels()
  const repos = useRepos()

  const [draft, setDraft] = useState('')
  const [repo, setRepo] = useState<Repo | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [open, setOpen] = useState<'mention' | 'model' | null>(null)
  const [mention, setMention] = useState<ActiveMention | null>(null)
  const [active, setActive] = useState(0)
  const [problem, setProblem] = useState<SendProblem | null>(null)
  const [installing, setInstalling] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const caretAfter = useRef<number | null>(null)

  // preselect: the user's default, else the server's default_model
  useEffect(() => {
    if (models.data && (model === null || !models.data.models.some((m) => m.id === model && m.available)))
      setModel(initialModel(models.data, me.default_model))
  }, [models.data, me.default_model, model])

  // grow with the text (up to the CSS max-height), and put the caret back after an edit
  useLayoutEffect(() => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
    if (caretAfter.current !== null) {
      el.setSelectionRange(caretAfter.current, caretAfter.current)
      caretAfter.current = null
    }
  }, [draft])

  const matches = useMemo(() => filterRepos(repos.data ?? [], mention?.query ?? ''), [repos.data, mention])
  const selectedModel = models.data?.models.find((m) => m.id === model)

  const send = useMutation({
    mutationFn: async (body: { message: string; repo: string | null; model: string | null }) => {
      if (!reply) return (await api.createSession(body)).id
      await api.followUp(reply.sessionId, { text: body.message, ...(body.repo ? { repo: body.repo } : {}) })
      return reply.sessionId
    },
    onSuccess: (id, body) => {
      qc.invalidateQueries({ queryKey: keys.sessions })
      qc.invalidateQueries({ queryKey: keys.usage })
      if (!reply) return navigate(`/c/${id}`)
      reply.onSent(body.message, body.repo)
      setDraft('')
      setRepo(null)
    },
    onError: (e) => {
      const p = sendProblem(e)
      setProblem(p)
      if (p.kind === 'model') qc.invalidateQueries({ queryKey: keys.models })
    },
  })

  const typed = extractRepo(draft, repos.data ?? [])
  const message = repo ? draft.trim() : typed.text
  const target = repo ?? typed.repo
  const working = reply?.live === true
  const canSend = message.length > 0 && !send.isPending && !working
  const stop = useMutation({
    mutationFn: () => api.stop(reply!.sessionId),
    onError: (e) => setProblem({ kind: 'other', message: messageOf(e) }),
  })

  function submit() {
    if (!canSend) return
    setProblem(null)
    setOpen(null)
    send.mutate({ message, repo: target?.full_name ?? null, model: reply ? null : model })
  }

  function onChange(value: string, caret: number) {
    setDraft(value)
    const m = activeMention(value, caret)
    setMention(m)
    setActive(0)
    setOpen(m ? 'mention' : open === 'mention' ? null : open)
  }

  function pick(r: Repo) {
    if (mention) {
      const next = removeMention(draft, mention)
      caretAfter.current = next.caret
      setDraft(next.text)
    }
    setRepo(r)
    setMention(null)
    setOpen(null)
    ta.current?.focus()
  }

  function openMention() {
    const sep = draft && !/\s$/.test(draft) ? ' @' : '@'
    const value = draft + sep
    caretAfter.current = value.length
    setDraft(value)
    setMention({ start: value.length - 1, end: value.length, query: '' })
    setActive(0)
    setOpen('mention')
    ta.current?.focus()
  }

  useImperativeHandle(handle, () => ({ mention: openMention }))

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing) return
    if (open === 'mention' && matches.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const step = e.key === 'ArrowDown' ? 1 : -1
        setActive((i) => (i + step + matches.length) % matches.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        pick(matches[Math.min(active, matches.length - 1)]!)
        return
      }
    }
    if (e.key === 'Escape' && open) {
      e.preventDefault()
      setOpen(null)
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
      return
    }
    if (e.key === 'Backspace' && !draft && repo) setRepo(null)
  }

  async function install() {
    setInstalling(true)
    rememberReturn('/')
    try {
      await goToGitHub(api.installUrl)
    } catch (e) {
      setProblem({ kind: 'other', message: messageOf(e) })
      setInstalling(false)
      setOpen(null)
    }
  }

  function fill(s: Suggestion) {
    setRepo(s.repo)
    caretAfter.current = s.text.length
    setDraft(s.text)
    setOpen(null)
    setMention(null)
    ta.current?.focus()
  }

  const below = hero && !mobile
  const hint = target || reply?.repo ? REPO_DISCLAIMER : DISCLAIMER
  const chips = suggestions.length > 0 && (
    <SuggestionChips suggestions={suggestions} mobile={mobile} onPick={fill} />
  )

  return (
    <div style={{ padding: mobile ? '8px 12px 14px' : hero ? '0 32px' : '0 32px 16px' }} className="shrink-0 bg-bg">
      {mobile && hero && chips}
      {problem && (
        <div className="mx-auto mb-3 w-full" style={{ maxWidth: hero ? 720 : 760 }}>
          <SendProblemCard problem={problem} />
        </div>
      )}
      <div className="relative mx-auto w-full" style={{ maxWidth: hero ? 720 : 760 }}>
        {open === 'mention' && (
          <ComposerPopover mobile={mobile} below={below} width={420} onClose={() => setOpen(null)} label="Mention a repo">
            {repos.isPending ? (
              <div className="px-3 py-3.5 text-sm text-muted">Loading repositories…</div>
            ) : repos.isError ? (
              <div className="px-3 py-3.5 text-sm text-bad">{messageOf(repos.error)}</div>
            ) : repos.data.length === 0 ? (
              <NoRepos linked={!!me.github_login} busy={installing} onInstall={install} />
            ) : (
              <MentionMenu
                repos={matches}
                query={mention?.query ?? ''}
                active={active}
                mobile={mobile}
                onPick={pick}
                onHover={setActive}
              />
            )}
          </ComposerPopover>
        )}
        {open === 'model' && models.data && (
          <ComposerPopover mobile={mobile} below={below} width={340} onClose={() => setOpen(null)} label="Choose a model">
            <ModelMenu
              models={models.data.models}
              selected={model}
              defaultId={models.data.default_model}
              rowPadding={mobile ? '13px 12px' : '9px 12px'}
              onPick={(id) => {
                setModel(id)
                setOpen(null)
                if (problem?.kind === 'model') setProblem(null)
                ta.current?.focus()
              }}
              onClose={() => {
                setOpen(null)
                ta.current?.focus()
              }}
            />
          </ComposerPopover>
        )}

        <div
          className="rounded-3xl border border-solid bg-card shadow-card transition-[border-color] duration-200"
          style={{ padding: '14px 12px 10px 18px', borderColor: open ? 'var(--accent)' : 'var(--line)' }}
        >
          <div className="flex flex-wrap items-start gap-1.5">
            {repo && (
              <span className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg bg-accent-bg pl-[9px] pr-1.5 text-[15px] font-medium text-accent">
                <RepoIcon size={13} />@{shortName(repo.full_name)}
                <button
                  type="button"
                  title="Remove"
                  aria-label={`Remove ${repo.full_name}`}
                  onClick={() => {
                    setRepo(null)
                    ta.current?.focus()
                  }}
                  className="flex size-[18px] items-center justify-center rounded-[5px] border-0 bg-transparent p-0 text-inherit"
                >
                  <X size={11} strokeWidth={2.4} />
                </button>
              </span>
            )}
            <textarea
              ref={ta}
              rows={1}
              value={draft}
              aria-label="Message Otto"
              aria-controls={open === 'mention' ? 'mention-list' : undefined}
              aria-activedescendant={open === 'mention' && matches.length ? `mention-${active}` : undefined}
              aria-autocomplete="list"
              placeholder={working ? 'Otto is working…' : reply ? 'Reply to Otto…' : 'Message Otto. Type @ to mention a repo.'}
              onChange={(e) => onChange(e.target.value, e.target.selectionStart)}
              onKeyDown={onKeyDown}
              className="max-h-[220px] min-w-[120px] flex-[1_1_180px] resize-none border-0 bg-transparent py-0.5 text-base leading-[1.55] text-text outline-none focus-visible:outline-none"
              style={{ minHeight: hero && !mobile ? 54 : 26, fontFamily: 'inherit' }}
            />
          </div>
          <div className="mt-2 flex items-center gap-2">
            {reply ? (
              // a chat keeps the model it started with (the gateway refuses another)
              <span title="A chat keeps the model it started with" className="-ml-2 flex h-8 items-center px-2.5 text-[13.5px] font-medium text-muted">
                {models.data?.models.find((m) => m.id === reply.model)?.label ?? reply.model ?? ''}
              </span>
            ) : (
              <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={open === 'model'}
                disabled={!models.data}
                onClick={() => setOpen(open === 'model' ? null : 'model')}
                className="-ml-2 flex h-8 items-center gap-1.5 rounded-[9px] border-0 px-2.5 text-[13.5px] font-medium text-muted hover:bg-hover"
                style={{ background: open === 'model' ? 'var(--sel)' : undefined }}
              >
                {selectedModel?.label ?? (models.isPending ? 'Models…' : 'No model')}
                <ChevronDown size={13} strokeWidth={2} />
              </button>
            )}
            <button
              type="button"
              title="Mention a repo"
              aria-label="Mention a repo"
              onClick={openMention}
              className="flex size-8 items-center justify-center rounded-[9px] border-0 bg-transparent text-muted hover:bg-hover"
            >
              <AtSign size={17} strokeWidth={1.7} />
            </button>
            <div className="flex-1" />
            {working ? (
              <button
                type="button"
                title="Stop"
                aria-label="Stop"
                disabled={stop.isPending}
                onClick={() => stop.mutate()}
                className="flex size-[34px] items-center justify-center rounded-full border-0 bg-text text-bg transition-[background] duration-200"
              >
                <Square size={13} fill="currentColor" strokeWidth={0} />
              </button>
            ) : (
              <button
                type="button"
                title="Send"
                aria-label="Send"
                disabled={!canSend}
                onClick={submit}
                className={cn('flex size-[34px] items-center justify-center rounded-full border-0 transition-[background] duration-200')}
                style={{ background: canSend ? 'var(--accent)' : 'var(--sel)', color: canSend ? '#fff' : 'var(--muted)' }}
              >
                <ArrowUp size={16} strokeWidth={2.2} />
              </button>
            )}
          </div>
        </div>
      </div>
      <div
        className="mx-auto box-content pt-2 text-center text-xs leading-4 text-muted text-balance"
        style={{ maxWidth: hero ? 720 : 760, minHeight: mobile ? 32 : 16 }}
      >
        {hint}
      </div>
      {!mobile && hero && chips}
    </div>
  )
}

function SuggestionChips({
  suggestions,
  mobile,
  onPick,
}: {
  suggestions: Suggestion[]
  mobile: boolean
  onPick: (s: Suggestion) => void
}) {
  const label = (s: Suggestion) => {
    if (!s.repo) return <>{s.text}</>
    const at = <span className="font-medium text-accent">@{shortName(s.repo.full_name)}</span>
    return s.mentionAtEnd ? (
      <>
        {s.text} in {at}
      </>
    ) : (
      <>
        {at} {s.text}
      </>
    )
  }
  if (mobile) {
    return (
      <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-2.5 [scrollbar-width:none]">
        {suggestions.map((s) => (
          <button
            key={s.text}
            type="button"
            onClick={() => onPick(s)}
            className="h-9 shrink-0 whitespace-nowrap rounded-[980px] border border-solid border-line bg-card px-3.5 text-sm text-text"
          >
            {label(s)}
          </button>
        ))}
      </div>
    )
  }
  return (
    <div className="mx-auto flex max-w-[720px] flex-wrap justify-center gap-2.5 pt-[22px]">
      {suggestions.map((s) => (
        <button
          key={s.text}
          type="button"
          onClick={() => onPick(s)}
          className="h-9 rounded-[980px] border border-solid border-line bg-transparent px-4 text-sm text-text transition-[background] duration-200 hover:bg-hover"
        >
          {label(s)}
        </button>
      ))}
    </div>
  )
}
