import { Check } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { Model } from '@/api/types'
import { groupModels, providerName } from './models'

/**
 * The model list, grouped by provider. Each row: the label, a "Default" tag on the server's
 * default model, a one-line description, and a check on the chosen one. An unavailable model is
 * dimmed, can't be picked, and shows its hint.
 */
export function ModelMenu({
  models,
  selected,
  defaultId,
  onPick,
  onClose,
  rowPadding = '9px 12px',
  autoFocus = true,
}: {
  models: Model[]
  selected: string | null
  defaultId: string | null
  onPick: (id: string) => void
  onClose?: () => void
  rowPadding?: string
  autoFocus?: boolean
}) {
  const enabled = models.filter((m) => m.available)
  const [active, setActive] = useState(() => Math.max(0, enabled.findIndex((m) => m.id === selected)))
  const listRef = useRef<HTMLDivElement>(null)
  const [moved, setMoved] = useState(false) // highlight a row only once the keyboard or mouse moves

  useEffect(() => {
    if (autoFocus) listRef.current?.focus()
  }, [autoFocus])

  function onKey(e: KeyboardEvent) {
    if (!enabled.length) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setMoved(true)
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i + step + enabled.length) % enabled.length)
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onPick(enabled[active]!.id)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose?.()
    }
  }

  const activeId = autoFocus ? enabled[active]?.id : undefined
  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Models"
      tabIndex={-1}
      aria-activedescendant={activeId ? `model-${cssId(activeId)}` : undefined}
      onKeyDown={onKey}
      className="outline-none"
    >
      {groupModels(models).map((g, gi) => (
        <div role="group" aria-label={providerName(g.provider)} key={g.provider}>
          <div className="text-xs font-semibold text-muted" style={{ padding: gi ? '12px 12px 4px' : '8px 12px 4px' }}>
            {providerName(g.provider)}
          </div>
          {g.models.map((m) => {
            const on = m.id === selected
            const isActive = moved && m.id === activeId
            return (
              <div
                key={m.id}
                id={`model-${cssId(m.id)}`}
                role="option"
                aria-selected={on}
                aria-disabled={!m.available || undefined}
                onClick={() => m.available && onPick(m.id)}
                onMouseEnter={() => {
                  if (!m.available) return
                  setMoved(true)
                  setActive(enabled.indexOf(m))
                }}
                className={`flex w-full items-start gap-3 rounded-[10px] text-left leading-[normal] text-text ${m.available ? 'hover:bg-hover' : ''}`}
                style={{
                  padding: rowPadding,
                  cursor: m.available ? 'pointer' : 'not-allowed',
                  background: isActive ? 'var(--hover)' : undefined,
                }}
              >
                <span className="min-w-0 flex-1" style={{ opacity: m.available ? 1 : 0.45 }}>
                  <span className="flex items-center gap-2">
                    <span className="text-[15px] font-medium">{m.label}</span>
                    {m.id === defaultId && (
                      <span className="rounded-md bg-tag px-[7px] py-px text-[11.5px] font-medium text-muted">Default</span>
                    )}
                  </span>
                  {m.description && <span className="mt-px block text-[13.5px] text-muted">{m.description}</span>}
                  {!m.available && (
                    <span className="mt-[3px] block text-[12.5px] italic text-muted">{m.hint || 'Unavailable right now.'}</span>
                  )}
                </span>
                <Check
                  size={16}
                  strokeWidth={2.2}
                  aria-hidden="true"
                  className="mt-[3px] shrink-0 text-accent"
                  style={{ opacity: on ? 1 : 0 }}
                />
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

const cssId = (id: string) => id.replace(/[^A-Za-z0-9_-]/g, '_')
