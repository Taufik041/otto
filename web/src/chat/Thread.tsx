import { useMutation } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { useModels } from '@/api/queries'
import { Mark } from '@/components/brand'
import { ModelMenu } from '@/composer/ModelMenu'
import { SendProblemCard } from '@/composer/SendProblemCard'
import { shortName } from '@/utils/mention'
import { Glyph, IC } from './icons'
import { Markdown } from './Markdown'
import { PrCard } from './PrCard'
import { ProposalCard } from './ProposalCard'
import type { Item, Step } from './reduce'
import { WorkBlock } from './WorkBlock'

export type ThreadProps = {
  sessionId: string
  /** the chat's model now */
  model: string | null
  items: Item[]
  live: boolean
  repo: string | null
  branch: string | null
  /** the follow-up just sent, until its own event arrives */
  sent: { text: string; repo: string | null } | null
  selectedStep: string | null
  onOpenStep: (s: Step) => void
  onOpenWorkspace: () => void
  onSeeChanges: (path: string) => void
  onMention: () => void
}

function UserBubble({ text, repo }: { text: string; repo: string | null }) {
  return (
    <div className="flex justify-end pb-6 animate-rise">
      <div className="max-w-[82%] whitespace-pre-wrap rounded-[20px] bg-bg2 px-4 py-2.5 text-base leading-[1.55] text-pretty [overflow-wrap:anywhere]">
        {repo && (
          <>
            <span className="inline-flex items-center rounded-[7px] bg-accent-bg px-[7px] font-medium text-accent">@{shortName(repo)}</span>{' '}
          </>
        )}
        {text}
      </div>
    </div>
  )
}

/** Otto's side: the small mark (first item of a turn only; it turns while Otto works), then the item. */
function Otto({ avatar, spinning, pb = 16, children }: { avatar: boolean; spinning: boolean; pb?: number; children: ReactNode }) {
  return (
    <div className="flex gap-3.5 animate-rise" style={{ paddingBottom: pb }}>
      <div className="w-[22px] shrink-0 pt-[3px]" style={{ visibility: avatar ? 'visible' : 'hidden' }}>
        <Mark size={22} className={spinning ? 'animate-[otto-spin_3.2s_linear_infinite]' : undefined} />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function ErrorCard({
  sessionId,
  title,
  message,
  switchModel,
  model,
}: {
  sessionId: string
  title: string
  message: string
  /** the model can't work: offer the picker, and retry on the one picked */
  switchModel: boolean
  model: string | null
}) {
  const models = useModels()
  const [picked, setPicked] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)
  const chosen = picked ?? model
  const retry = useMutation({ mutationFn: () => api.retry(sessionId, chosen && chosen !== model ? chosen : undefined) })
  const label = models.data?.models.find((m) => m.id === chosen)?.label ?? chosen
  return (
    <div role="alert" className="rounded-[18px] border border-solid border-line bg-card px-5 py-[18px]">
      <div className="flex items-start gap-3">
        <Glyph d={IC.alert} size={18} width={1.8} className="mt-0.5 shrink-0 text-bad" />
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">{title}</div>
          <div className="mt-[3px] text-[15px] leading-normal text-muted text-pretty">{message}</div>
          <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
            {switchModel && (
              <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={picking}
                disabled={!models.data}
                onClick={() => setPicking(!picking)}
                className="inline-flex h-9 items-center gap-1.5 rounded-[980px] border border-solid border-line bg-transparent px-3.5 text-[14px] text-text hover:bg-hover"
              >
                {label}
                <Glyph d={IC.chevDown} size={13} width={2} />
              </button>
            )}
            <button
              type="button"
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
              className="inline-flex h-9 items-center gap-[7px] rounded-[980px] border-0 bg-accent px-4 text-[14.5px] text-white hover:bg-accent-h disabled:opacity-60"
            >
              <Glyph d={IC.retry} size={14} width={2} />
              Retry
            </button>
          </div>
          {switchModel && picking && models.data && (
            <div className="mt-3 rounded-[14px] border border-solid border-line p-1.5 animate-pop">
              <ModelMenu
                models={models.data.models}
                selected={chosen}
                defaultId={models.data.default_model}
                autoFocus={false}
                onPick={(id) => {
                  setPicked(id)
                  setPicking(false)
                }}
                onClose={() => setPicking(false)}
              />
            </div>
          )}
          {retry.isError && <div className="mt-2 text-sm text-bad">{messageOf(retry.error)}</div>}
        </div>
      </div>
    </div>
  )
}

/** "Switched to GPT-4.1 mini": a quiet divider where the chat moved to another model. */
function ModelDivider({ to }: { to: string }) {
  const models = useModels()
  const label = models.data?.models.find((m) => m.id === to)?.label ?? to
  return (
    <div role="separator" aria-label={`Switched to ${label}`} className="flex items-center gap-3 pb-6 text-[13px] text-muted animate-rise">
      <span className="h-px flex-1 bg-hair" />
      <span>Switched to {label}</span>
      <span className="h-px flex-1 bg-hair" />
    </div>
  )
}

export function Thread(p: ThreadProps) {
  const last = p.items.length - 1
  // the avatar that turns while Otto works: the latest one shown
  let spinAt = -1
  if (p.live) for (let i = last; i >= 0; i--) if ('avatar' in p.items[i]! && (p.items[i] as { avatar: boolean }).avatar) {
    spinAt = i
    break
  }
  // the pending turn's message is the one just sent; before its turn shows up, it goes last
  const pendingTurn = p.items.some((i) => i.kind === 'user' && i.text === null)

  return (
    <>
      {p.items.map((it, i) => {
        switch (it.kind) {
          case 'user': {
            if (it.text === null) return p.sent ? <UserBubble key={it.id} text={p.sent.text} repo={p.sent.repo} /> : null
            return <UserBubble key={it.id} text={it.text} repo={it.repo} />
          }
          case 'prose':
            return (
              <Otto key={it.id} avatar={it.avatar} spinning={i === spinAt} pb={i === last ? 32 : 16}>
                <Markdown text={it.text} />
              </Otto>
            )
          case 'thinking':
            return (
              <Otto key={it.id} avatar spinning>
                <span className="text-base leading-[1.65] text-muted animate-pulse-dot">Thinking…</span>
              </Otto>
            )
          case 'work':
            return (
              <Otto key={it.id} avatar={it.avatar} spinning={i === spinAt}>
                <WorkBlock
                  block={it.block}
                  repo={p.repo ?? ''}
                  branch={p.branch}
                  selected={p.selectedStep}
                  onOpenStep={p.onOpenStep}
                  onOpenWorkspace={p.onOpenWorkspace}
                />
              </Otto>
            )
          case 'pr':
            return (
              <Otto key={it.id} avatar={false} spinning={false}>
                <PrCard pr={it.pr} onSeeChanges={() => p.onSeeChanges(it.pr.firstFile!)} />
              </Otto>
            )
          case 'model':
            return <ModelDivider key={it.id} to={it.to} />
          case 'proposal':
            return (
              <Otto key={it.id} avatar={false} spinning={false}>
                <ProposalCard sessionId={p.sessionId} proposal={it.proposal} state={it.state} live={p.live} />
              </Otto>
            )
          case 'stopped':
            return (
              <div key={it.id} className="flex items-center justify-center gap-[7px] pb-6 text-[13px] text-muted animate-rise">
                <Glyph d={IC.stop} size={13} fill />
                You stopped Otto. Nothing after that step ran.
              </div>
            )
          case 'error':
            return (
              <Otto key={it.id} avatar spinning={false}>
                <ErrorCard sessionId={p.sessionId} title={it.title} message={it.message} switchModel={it.switchModel} model={p.model} />
              </Otto>
            )
          case 'limit':
            return (
              <Otto key={it.id} avatar spinning={false}>
                <SendProblemCard problem={{ kind: 'limit', limit: { code: 'daily_limit', used: it.used, limit: it.limit, resets_at: it.resetsAt } }} />
              </Otto>
            )
          case 'nudge':
            return (
              <Otto key={it.id} avatar={false} spinning={false}>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3.5 gap-y-2.5 rounded-[14px] border border-solid border-line py-3 pl-4 pr-3.5">
                  <Glyph d={IC.at} className="shrink-0 text-accent" />
                  <span className="flex-[1_1_220px] text-[14.5px]">Mention a repo with @ and I'll work on it.</span>
                  <button
                    type="button"
                    onClick={p.onMention}
                    className="h-8 shrink-0 rounded-[980px] border border-solid border-line bg-transparent px-3.5 text-[13.5px] text-text hover:bg-hover"
                  >
                    Mention a repo
                  </button>
                </div>
              </Otto>
            )
        }
      })}
      {p.sent && !pendingTurn && <UserBubble text={p.sent.text} repo={p.sent.repo} />}
    </>
  )
}
