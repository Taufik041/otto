import { useEffect, useRef, type CSSProperties } from 'react'
import { ownerOf, shortName } from '@/utils/mention'
import { CodeLine } from './Code'
import { languageOf, parseDiff } from './diff'
import { useTokens } from './highlight'
import { Glyph, IC } from './icons'
import type { FileChange, FileEntry, TermEntry } from './reduce'

export type WorkspaceTab = 'changes' | 'terminal'
export type WorkspaceState = { tab: WorkspaceTab; path: string | null; entry: string | null }

const GUTTER: CSSProperties = { flex: '0 0 44px', textAlign: 'right', paddingRight: 10, color: 'var(--gutter)', userSelect: 'none' }

/**
 * The workspace panel: what Otto changed (Changes) and every command it ran (Terminal). Read-only.
 * Desktop: beside the chat, resizable. Phones: a full-screen sheet.
 */
export function Workspace({
  repo,
  branch,
  files,
  terminal,
  state,
  onState,
  onClose,
  mobile,
}: {
  repo: string
  branch: string | null
  files: FileChange[]
  terminal: TermEntry[]
  state: WorkspaceState
  onState: (s: WorkspaceState) => void
  onClose: () => void
  mobile: boolean
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const file = files.find((f) => f.path === state.path) ?? files.find((f) => f.kind !== 'Read') ?? files[0] ?? null

  // the step picked in the chat: bring its entry into view
  useEffect(() => {
    if (!state.entry) return
    const el = scroller.current?.querySelector(`[data-entry="${CSS.escape(state.entry)}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [state.entry, state.tab, state.path])

  return (
    <section
      aria-label="Workspace"
      className="flex min-w-0 flex-col border-0 border-solid bg-bg"
      style={
        mobile
          ? { position: 'fixed', inset: 0, zIndex: 70, animation: 'otto-sheet .35s cubic-bezier(.2,.8,.2,1) both' }
          : { position: 'relative', height: '100%', borderLeftWidth: 1, borderColor: 'var(--line)', animation: 'otto-slide .35s cubic-bezier(.2,.8,.2,1) both' }
      }
    >
      <div
        className="flex shrink-0 items-center gap-3 border-0 border-b border-solid border-hair"
        style={{ padding: mobile ? '10px 12px 10px 18px' : '10px 14px 10px 20px' }}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-semibold">
            {ownerOf(repo)}/{shortName(repo)}
          </div>
          {branch && <div className="font-mono text-xs text-muted">{branch}</div>}
        </div>
        <button
          type="button"
          title="Close"
          aria-label="Close workspace"
          onClick={onClose}
          className="flex size-[34px] shrink-0 items-center justify-center rounded-full border-0 bg-tag text-text"
        >
          <Glyph d={IC.x} size={14} width={2.2} />
        </button>
      </div>
      <div className="shrink-0 border-0 border-b border-solid border-hair px-4 py-3">
        <div role="tablist" className="flex gap-0.5 rounded-[10px] bg-sel p-0.5">
          {(['changes', 'terminal'] as const).map((t) => {
            const on = state.tab === t
            return (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => onState({ ...state, tab: t })}
                className="h-[30px] flex-1 rounded-lg border-0 text-[13.5px] font-medium transition-[background] duration-200"
                style={{ background: on ? 'var(--card)' : 'transparent', color: on ? 'var(--text)' : 'var(--muted)', boxShadow: on ? '0 1px 3px rgba(0,0,0,.12)' : 'none' }}
              >
                {t === 'changes' ? 'Changes' : 'Terminal'}
              </button>
            )
          })}
        </div>
      </div>
      <div ref={scroller} className="min-h-0 flex-1 overflow-auto bg-bg">
        {state.tab === 'changes' ? (
          <div className="flex flex-col gap-3.5 p-4">
            {files.length === 0 ? (
              <div className="px-4 py-12 text-center text-sm text-muted">No files touched yet.</div>
            ) : (
              <>
                <div className="overflow-hidden rounded-[14px] border border-solid border-line">
                  {files.map((f, i) => (
                    <button
                      key={f.path}
                      type="button"
                      aria-current={f === file ? 'true' : undefined}
                      onClick={() => onState({ ...state, path: f.path, entry: null })}
                      className="flex w-full items-center gap-2.5 border-0 px-3.5 py-2.5 text-left text-text"
                      style={{ borderTop: i ? '1px solid var(--hair)' : 'none', background: f === file ? 'var(--sel)' : 'transparent' }}
                    >
                      <Glyph d={f.kind === 'Read' ? IC.file : IC.edit} size={14} width={1.6} className="shrink-0 text-muted" />
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{f.path}</span>
                      <span className="shrink-0 text-xs text-muted">{f.kind}</span>
                      {f.kind !== 'Read' && <span className="shrink-0 font-mono text-xs text-ok">+{f.add}</span>}
                      {f.kind !== 'Read' && f.del > 0 && <span className="shrink-0 font-mono text-xs text-bad">−{f.del}</span>}
                    </button>
                  ))}
                </div>
                {file && <FileView file={file} selected={state.entry} />}
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-3 p-4">
            {terminal.length === 0 && <div className="px-4 py-12 text-center text-sm text-muted">No commands yet.</div>}
            {terminal.map((t) => (
              <Command key={t.id} entry={t} selected={state.entry === t.id} />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function FileView({ file, selected }: { file: FileChange; selected: string | null }) {
  const edits = file.entries.filter((e) => e.type === 'diff')
  const shown = file.kind === 'Read' ? file.entries : edits
  const reads = file.entries.filter((e): e is Extract<FileEntry, { type: 'read' }> => e.type === 'read')
  const note =
    file.kind === 'Read'
      ? reads.length === 1
        ? `Read · lines ${reads[0]!.start}–${reads[0]!.start + Math.max(0, reads[0]!.text.replace(/\n$/, '').split('\n').length - 1)}`
        : `Read ${reads.length} times`
      : edits.length > 1
        ? `${edits.length} edits`
        : 'Unified diff'
  return (
    <div className="flex flex-col overflow-hidden rounded-[14px] border border-solid border-line bg-card">
      <div className="flex items-center gap-2.5 border-0 border-b border-solid border-hair px-3.5 py-2.5">
        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{file.path}</span>
        <span className="shrink-0 text-xs text-muted">{note}</span>
      </div>
      <div className="overflow-x-auto pb-2.5 pt-1.5 font-mono text-[12.5px] leading-[1.8] text-text">
        <div className="inline-flex min-w-full flex-col">
          {shown.map((e, i) => (
            <div key={e.id} data-entry={e.id} style={{ borderTop: i ? '1px solid var(--hair)' : 'none', background: selected === e.id && shown.length > 1 ? 'color-mix(in srgb, var(--accent) 5%, transparent)' : undefined }}>
              {e.type === 'diff' ? <Diff diff={e.diff} truncated={e.truncated} lang={languageOf(file.path)} /> : <Slice start={e.start} text={e.text} lang={languageOf(file.path)} />}
            </div>
          ))}
          {shown.length === 0 && <div className="px-3.5 py-2 text-muted">No diff was recorded for this file.</div>}
        </div>
      </div>
    </div>
  )
}

function Diff({ diff, truncated, lang }: { diff: string; truncated: boolean; lang: string | null }) {
  const rows = parseDiff(diff)
  const code = rows.filter((r) => r.type === 'ctx' || r.type === 'add' || r.type === 'del').map((r) => r.text)
  const tokens = useTokens(code.join('\n'), lang, true)
  let n = 0
  return (
    <>
      {rows.map((r, i) => {
        if (r.type === 'hunk')
          return (
            <div key={i} className="flex bg-[var(--hunk)] text-muted">
              <span className="shrink-0 basis-[108px]" />
              <span className="whitespace-pre pr-5">{r.text}</span>
            </div>
          )
        if (r.type === 'note')
          return (
            <div key={i} className="flex text-muted">
              <span className="shrink-0 basis-[108px]" />
              <span className="whitespace-pre pr-5 italic">{r.text}</span>
            </div>
          )
        const add = r.type === 'add'
        const del = r.type === 'del'
        const lineTokens = tokens?.[n++]
        return (
          <div key={i} className="flex" style={{ background: add ? 'var(--add-bg)' : del ? 'var(--del-bg)' : 'transparent' }}>
            <span style={GUTTER}>{r.old ?? ''}</span>
            <span style={GUTTER}>{r.new ?? ''}</span>
            <span className="shrink-0 basis-5 text-center" style={{ color: add ? 'var(--ok)' : 'var(--bad)' }}>
              {add ? '+' : del ? '−' : ''}
            </span>
            <span className="whitespace-pre pr-5">
              <CodeLine text={r.text} tokens={lineTokens} />
            </span>
          </div>
        )
      })}
      {truncated && <div className="px-3.5 py-1 text-muted">The rest of this diff was too long to keep.</div>}
    </>
  )
}

function Slice({ start, text, lang }: { start: number; text: string; lang: string | null }) {
  const lines = text.replace(/\n$/, '').split('\n')
  const tokens = useTokens(lines.join('\n'), lang, true)
  return (
    <>
      {lines.map((l, i) => (
        <div key={i} className="flex">
          <span style={GUTTER}>{start + i}</span>
          <span className="whitespace-pre pl-2.5 pr-5">
            <CodeLine text={l} tokens={tokens?.[i]} />
          </span>
        </div>
      ))}
    </>
  )
}

/** pytest's FAILED / error lines in red, its summary in green or red; the rest as printed. */
function outputColor(line: string): string | undefined {
  if (/^(FAILED|ERROR)\b|^E\s{3}|Error:|^_{3,}.*_{3,}$/.test(line)) return 'var(--bad)'
  if (/^=+ .*(failed|error).* =+$|\d+ failed/.test(line)) return 'var(--bad)'
  if (/^=*\s*\d+ passed.* in [\d.]+s/.test(line)) return 'var(--ok)'
  return undefined
}

function Command({ entry, selected }: { entry: TermEntry; selected: boolean }) {
  const out = [entry.stdout, entry.stderr].filter((s) => s.trim()).join('\n').replace(/\n$/, '')
  const ok = entry.exit === 0
  const passed = ok && entry.tests && !entry.tests.failed && !entry.tests.errors ? entry.tests : null
  return (
    <div
      data-entry={entry.id}
      className="overflow-hidden rounded-[14px] border border-solid bg-card transition-[border-color,box-shadow] duration-300 animate-[otto-rise_.4s_ease-out_both]"
      style={{ borderColor: selected ? 'var(--accent)' : 'var(--line)', boxShadow: selected ? '0 0 0 3px var(--accent-bg)' : 'none' }}
    >
      <div className="flex items-start gap-2.5 border-0 border-b border-solid border-hair px-3.5 py-2.5 font-mono text-[12.5px]">
        <span className="text-muted">$</span>
        <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{entry.cmd}</span>
        <span
          className="inline-flex shrink-0 items-center gap-[5px] text-xs"
          style={{ color: entry.exit === null ? 'var(--muted)' : ok ? 'var(--ok)' : 'var(--bad)' }}
        >
          <Glyph
            d={entry.exit === null ? IC.spin : ok ? IC.check : IC.x}
            size={12}
            width={2.6}
            className={entry.exit === null && entry.live ? 'animate-spin-slow' : undefined}
          />
          {entry.exit === null ? (entry.live ? 'running' : 'stopped') : `exit ${entry.exit}`}
        </span>
      </div>
      {entry.exit !== null && out && (
        <div className="overflow-x-auto px-3.5 pb-3 pt-2.5 font-mono text-[12.5px] leading-[1.7] text-text">
          <div className="inline-flex min-w-full flex-col">
            {out.split('\n').map((l, i) => (
              <div key={i} className="whitespace-pre" style={{ color: outputColor(l) }}>
                {l || ' '}
              </div>
            ))}
          </div>
        </div>
      )}
      {passed && (
        <div className="px-3.5 pb-3.5">
          <span className="inline-flex items-center gap-2.5 rounded-xl bg-ok-bg py-[9px] pl-3 pr-4 text-ok">
            <Glyph d={IC.checkCircle} size={20} width={1.8} />
            <span className="text-xl font-semibold leading-none tracking-[-0.015em]">{passed.passed} passed</span>
            {passed.duration && <span className="font-mono text-xs text-muted">{passed.duration}</span>}
          </span>
        </div>
      )}
    </div>
  )
}
