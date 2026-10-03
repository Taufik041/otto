import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from '@/theme/ThemeProvider'
import type { ThemeChoice } from '@/theme/theme'

const OPTIONS: [ThemeChoice, string, typeof Sun][] = [
  ['light', 'Light', Sun],
  ['dark', 'Dark', Moon],
  ['system', 'System', Monitor],
]

/** The profile menu's segmented Light / Dark / System control. */
export function ThemeSwitch() {
  const { choice, setChoice } = useTheme()
  return (
    <div role="radiogroup" aria-label="Theme" className="flex gap-0.5 rounded-lg bg-sel p-0.5">
      {OPTIONS.map(([id, label, Icon]) => {
        const on = choice === id
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={on}
            title={label}
            aria-label={label}
            onClick={() => setChoice(id)}
            className="flex h-6 w-7 items-center justify-center rounded-md border-0"
            style={{
              background: on ? 'var(--card)' : 'transparent',
              color: on ? 'var(--text)' : 'var(--muted)',
              boxShadow: on ? '0 1px 3px rgba(0,0,0,.12)' : 'none',
            }}
          >
            <Icon size={14} strokeWidth={1.7} />
          </button>
        )
      })}
    </div>
  )
}
