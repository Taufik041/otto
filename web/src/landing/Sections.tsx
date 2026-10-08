import { useMemo, useState, type ReactNode } from 'react'
import type { Repo } from '@/api/types'
import { Glyph, IC } from '@/chat/icons'
import { PrActionsContext } from '@/chat/prActions'
import { PrCard } from '@/chat/PrCard'
import { ProposalCard } from '@/chat/ProposalCard'
import { emptyState, reduce, view, type Item } from '@/chat/reduce'
import { WorkBlock } from '@/chat/WorkBlock'
import { Workspace } from '@/chat/Workspace'
import { GitHubIcon } from '@/components/brand'
import { RepoIcon } from '@/components/icons'
import { MentionMenu } from '@/composer/MentionMenu'
import { ModelMenu } from '@/composer/ModelMenu'
import { BRANCH, MODELS, REPO } from '@/fixtures/session.js'
import { cn } from '@/utils/cn'
import { CODE_URL } from './config'
import { finalFrame, frameAt, PROPOSED_AT } from './replay'

const noop = () => {}
const STILL = { create: () => new Promise<never>(() => {}), decline: () => new Promise<never>(() => {}) }

/** The replay's session at `t` ms (Infinity: all of it), as the app's view; it began `t` ago. */
function useViewAt(t: number) {
  const [now] = useState(() => Date.now())
  return useMemo(() => {
    const start = now - (Number.isFinite(t) ? t : 30_000)
    const f = Number.isFinite(t) ? frameAt(t, start) : finalFrame(start)
    return view(reduce(emptyState(), f.events))
  }, [t, now])
}
const find = <K extends Item['kind']>(items: Item[], kind: K) => items.find((i) => i.kind === kind) as Extract<Item, { kind: K }> | undefined

/** Two-tone: the first line in the tertiary gray, the second in text. */
export function TwoTone({ first, second, size, className }: { first: string; second: string; size: string; className?: string }) {
  return (
    // the size first: tailwind-merge drops a line-height that comes before a font size
    <h2 className={cn(size, 'm-0 font-normal leading-[1.06] tracking-[-0.03em]', className)}>
      <span className="block text-ter">{first}</span>
      <span className="block">{second}</span>
    </h2>
  )
}

/** A real piece of the app, as a still illustration (inert: nothing in it can be used). */
function Vignette({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div inert className={cn('w-full min-w-0 rounded-[20px] bg-bg2', className)}>
      <PrActionsContext.Provider value={STILL}>{children}</PrActionsContext.Provider>
    </div>
  )
}

const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString()
const REPOS: Repo[] = [
  { full_name: REPO, private: true, updated_at: ago(2), default_branch: 'main', installation_id: 1 },
  { full_name: 'Taufik041/portfolio', private: false, updated_at: ago(72), default_branch: 'main', installation_id: 1 },
]

// --- the stack marquee ---------------------------------------------------------------------

const STACK: [string, string][] = [
  ['Kubernetes', 'font-medium tracking-[-0.02em] text-[21px]'],
  ['RabbitMQ', 'font-medium tracking-[-0.04em] text-[21px]'],
  ['PostgreSQL', 'text-[20px]'],
  ['FastAPI', 'font-mono font-medium tracking-[-0.02em] text-[18px]'],
  ['React', 'tracking-[-0.03em] text-[22px]'],
  ['GitHub App', 'font-medium tracking-[-0.02em] text-[20px]'],
  ['OpenRouter', 'font-mono text-[18px]'],
  ['OpenAI', 'font-medium tracking-[-0.03em] text-[21px]'],
]

export function Marquee() {
  return (
    <section
      aria-label="Built with Kubernetes, RabbitMQ, PostgreSQL, FastAPI, React, a GitHub App, OpenRouter and OpenAI"
      className="flex h-[88px] items-center overflow-hidden border-0 border-y border-solid border-hair [mask-image:linear-gradient(90deg,transparent,#000_14%,#000_86%,transparent)]"
    >
      <div aria-hidden="true" className="flex shrink-0 items-center animate-[otto-marquee_90s_linear_infinite]">
        {[...STACK, ...STACK].map(([name, style], i) => (
          <span key={i} className={cn('shrink-0 whitespace-nowrap px-9 text-ter', style)}>
            {name}
          </span>
        ))}
      </div>
    </section>
  )
}

// --- how it works --------------------------------------------------------------------------

function Step({ n, title, body, reverse, mobile, children }: {
  n: string; title: string; body: string; reverse?: boolean; mobile: boolean; children: ReactNode
}) {
  return (
    <div className={cn('flex items-center', mobile ? 'flex-col gap-6' : reverse ? 'flex-row-reverse gap-16' : 'flex-row gap-16')}>
      <div className="w-full min-w-0 flex-1">
        <div className="text-[32px] tracking-[-0.03em] text-ter">{n}</div>
        <h3 className="m-0 mt-3.5 text-2xl font-normal tracking-[-0.03em]">{title}</h3>
        <p className="m-0 mt-2 max-w-[36ch] text-base leading-normal text-muted">{body}</p>
      </div>
      <Vignette className={cn('flex-[1.25]', mobile ? 'p-5' : 'p-9')}>{children}</Vignette>
    </div>
  )
}

export function HowItWorks({ mobile }: { mobile: boolean }) {
  const working = useViewAt(9_500)
  const proposed = useViewAt(PROPOSED_AT + 100)
  const block = find(working.items, 'work')
  const proposal = find(proposed.items, 'proposal')
  return (
    <section id="how" className={cn('scroll-mt-14 border-0 border-b border-solid border-hair', mobile ? 'py-[72px]' : 'py-[120px]')}>
      <div className={cn('mx-auto max-w-[1200px]', mobile ? 'px-5' : 'px-12')}>
        <TwoTone first="Three steps." second="From a sentence to a pull request." size={mobile ? 'text-[30px]' : 'text-[40px]'} />
        <div className={cn('flex flex-col', mobile ? 'mt-10 gap-14' : 'mt-16 gap-24')}>
          <Step n="01" title="Mention a repo" body="Type @ and pick a repository you connected." mobile={mobile}>
            <div className="max-w-[380px] rounded-[14px] border border-solid border-line bg-card p-1.5 shadow-pop">
              <MentionMenu repos={REPOS} query="" active={0} mobile={false} onPick={noop} onHover={noop} />
            </div>
            <div className="mt-2.5 rounded-[18px] border border-solid border-line bg-card px-3.5 py-3 text-[15px]">
              <span className="mr-1.5 inline-flex items-center gap-1 rounded-md bg-accent-bg px-1.5 font-medium text-accent">
                <RepoIcon size={12} />@otto_test
              </span>
              fix the failing tests
            </div>
          </Step>
          <Step n="02" title="Watch it work" body="Every command, diff and test run, live." reverse mobile={mobile}>
            {block && (
              <WorkBlock block={block.block} repo={REPO} branch={BRANCH} selected={null} onOpenStep={noop} onOpenWorkspace={noop} />
            )}
          </Step>
          <Step n="03" title="Approve the PR" body="Nothing reaches GitHub until you say so." mobile={mobile}>
            {proposal && <ProposalCard sessionId="still" proposal={proposal.proposal} state="proposed" live={false} />}
          </Step>
        </div>
      </div>
    </section>
  )
}

// --- the bento -----------------------------------------------------------------------------

function Tile({ big, title, body, mobile, children, art }: {
  big?: boolean; title: string; body: string; mobile: boolean; children: ReactNode; art?: string
}) {
  return (
    <div
      className="flex flex-col overflow-hidden rounded-[20px] bg-bg2"
      style={{ gridColumn: mobile ? 'auto' : big ? 'span 3' : 'span 2' }}
    >
      <div inert className={cn('flex flex-1', art)}>
        <PrActionsContext.Provider value={STILL}>{children}</PrActionsContext.Provider>
      </div>
      <div className="border-0 border-t border-solid border-hair px-6 pb-6 pt-5">
        <h3 className="m-0 text-xl font-normal tracking-[-0.02em]">{title}</h3>
        <p className="m-0 mt-1 text-[15px] text-muted">{body}</p>
      </div>
    </div>
  )
}

export function Bento({ mobile }: { mobile: boolean }) {
  const changes = useViewAt(11_500)
  const opened = useViewAt(Infinity)
  const setup = useViewAt(0)
  const pr = find(opened.items, 'pr')
  const sandbox = find(setup.items, 'work')
  return (
    <section className={cn('border-0 border-b border-solid border-hair', mobile ? 'py-[72px]' : 'py-[120px]')}>
      <div className={cn('mx-auto max-w-[1200px]', mobile ? 'px-5' : 'px-12')}>
        <TwoTone first="Small fixes, done properly." second="You stay in charge of every change." size={mobile ? 'text-[30px]' : 'text-[40px]'} />
        <div className={cn('grid gap-4', mobile ? 'mt-10 grid-cols-1' : 'mt-16 grid-cols-6')}>
          <Tile big mobile={mobile} title="Live work view" body="See each file change and every command's output as it happens." art="px-6 pt-6">
            <div className="h-[240px] w-full overflow-hidden rounded-t-[14px] border border-b-0 border-solid border-line [&>section]:!animate-none [&>section]:!border-l-0">
              <Workspace repo={REPO} branch={BRANCH} files={changes.files} terminal={changes.terminal}
                state={{ tab: 'changes', path: null, entry: null }} onState={noop} onClose={noop} mobile={false} />
            </div>
          </Tile>
          <Tile big mobile={mobile} title="You approve every PR" body="Otto proposes the change. It only opens on GitHub when you click Create."
            art="items-center justify-center p-6 min-h-[244px]">
            <div className="w-full max-w-[420px]">{pr && <PrCard pr={pr.pr} onSeeChanges={noop} />}</div>
          </Tile>
          <Tile mobile={mobile} title="Pick up weeks later" body="A follow-up adds commits to the same PR." art="flex-col justify-center gap-2.5 p-[22px] min-h-[180px]">
            <div className="max-w-[90%] self-end rounded-2xl bg-card px-3.5 py-2 text-[13.5px] shadow-[0_0_0_1px_var(--hair)]">also add a test for exactly 11 units</div>
            <div className="flex items-center gap-2 text-[13px] text-muted">
              <Glyph d={IC.pr} size={14} className="text-ok" />
              Pull request updated · #9 · <span className="font-mono text-ok">+4</span>
            </div>
          </Tile>
          <Tile mobile={mobile} title="Your choice of model" body="Switch models in the composer, even mid-chat." art="items-center p-[22px] min-h-[180px]">
            <div className="w-full rounded-[14px] border border-solid border-line bg-card p-1.5">
              <ModelMenu models={MODELS.models} selected={MODELS.default_model} defaultId={MODELS.default_model} onPick={noop} autoFocus={false} />
            </div>
          </Tile>
          <Tile mobile={mobile} title="A fresh sandbox for every task" body="Each task runs in its own isolated container." art="flex-col justify-center gap-2 p-[22px] min-h-[180px]">
            {sandbox && <WorkBlock block={sandbox.block} repo={REPO} branch={BRANCH} selected={null} onOpenStep={noop} onOpenWorkspace={noop} />}
            <div className="px-1 font-mono text-xs text-ter">cleaned up when the task ends</div>
          </Tile>
        </div>
      </div>
    </section>
  )
}

// --- architecture --------------------------------------------------------------------------

const NODES: [string, string][][] = [
  [['Browser', 'React app']],
  [['Gateway', 'FastAPI']],
  [['Postgres', 'event log'], ['RabbitMQ', 'message bus']],
  [['Brain workers', 'agent loop']],
  [['Sandboxes', 'Kubernetes']],
  [['GitHub App', 'PRs you approve']],
]

export function Architecture({ mobile }: { mobile: boolean }) {
  return (
    <section id="architecture" className={cn('scroll-mt-14 border-0 border-b border-solid border-hair', mobile ? 'py-[72px]' : 'py-[120px]')}>
      <div className={cn('mx-auto max-w-[1200px]', mobile ? 'px-5' : 'px-12')}>
        <TwoTone first="Built like real infrastructure." second="Because it is." size={mobile ? 'text-[30px]' : 'text-[40px]'} />
        <figure
          aria-label="Browser to Gateway; the Gateway writes to Postgres (the event log) and RabbitMQ (the message bus); brain workers and sandboxes on Kubernetes talk over the bus; the GitHub App opens the PRs you approve."
          className={cn('m-0 rounded-[20px] bg-bg2', mobile ? 'mt-10 p-5' : 'mt-16 px-7 py-10')}
        >
          <div className={cn('flex items-stretch justify-center gap-2.5', mobile ? 'flex-col' : 'flex-row')}>
            {NODES.map((boxes, i) => (
              <div key={i} className={cn('flex flex-1 items-center gap-2.5', mobile ? 'flex-col' : 'flex-row')}>
                <div className="flex w-full flex-1 flex-col gap-2">
                  {boxes.map(([name, sub]) => (
                    <div key={name} className="rounded-[14px] border border-solid border-line bg-card p-3.5 text-center shadow-card">
                      <div className="text-[15px]">{name}</div>
                      <div className="mt-0.5 font-mono text-[11.5px] text-muted">{sub}</div>
                    </div>
                  ))}
                </div>
                {i < NODES.length - 1 && (
                  <span aria-hidden="true" className="shrink-0 text-base text-ter" style={{ transform: mobile ? 'rotate(90deg)' : 'none' }}>
                    {i === 3 ? '⇄' : '→'}
                  </span>
                )}
              </div>
            ))}
          </div>
        </figure>
        <div className={cn('mt-10 grid gap-x-8 gap-y-6', mobile ? 'grid-cols-1' : 'grid-cols-3')}>
          {[
            ['Event-sourced sessions', 'Every step is an event in Postgres, so a chat replays exactly, even after a reconnect.'],
            ['A message bus in the middle', 'RabbitMQ carries actions from the brain to the sandbox and results back.'],
            ['Human-approved PRs', 'The GitHub App only pushes and opens a pull request after you approve it.'],
          ].map(([h, p]) => (
            <div key={h}>
              <h3 className="m-0 text-lg font-normal tracking-[-0.02em]">{h}</h3>
              <p className="m-0 mt-1.5 text-[15px] leading-normal text-muted">{p}</p>
            </div>
          ))}
        </div>
        <a
          href={CODE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-9 inline-flex h-[42px] items-center gap-2 rounded-full border border-solid border-line px-5 text-base text-text hover:bg-hover hover:text-text"
        >
          <GitHubIcon size={16} />
          Read the code on GitHub
        </a>
      </div>
    </section>
  )
}
