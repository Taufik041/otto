import { useTheme } from '@/theme/ThemeProvider'
import type { ThemeChoice } from '@/theme/theme'
import { useIsMobile } from '@/hooks/useMediaQuery'

// the tiles draw each theme's own colors, whatever the current theme
const TILE = {
  light: { bg: '#FBFCFD', side: '#F5F7FA', line: 'rgba(15,23,42,.10)', accent: '#0071E3' },
  dark: { bg: '#111318', side: '#16191F', line: 'rgba(255,255,255,.10)', accent: '#2997FF' },
}
type Colors = (typeof TILE)['light']

function Preview({ c, sidebar = true }: { c: Colors; sidebar?: boolean }) {
  return (
    <>
      <span className="shrink-0 basis-[30%]" style={{ background: c.side, borderRight: `1px solid ${c.line}` }}>
        {sidebar && (
          <span className="flex flex-col gap-1.5 px-2 py-3">
            {[70, 90, 60].map((w) => (
              <span key={w} className="h-[5px] rounded-[9px]" style={{ width: `${w}%`, background: c.line }} />
            ))}
          </span>
        )}
      </span>
      <span className="flex flex-1 flex-col gap-[7px] px-3 py-3.5">
        <span className="h-3 w-[48%] self-end rounded-[9px]" style={{ background: c.side }} />
        <span className="h-[5px] w-[80%] rounded-[9px]" style={{ background: c.line }} />
        <span className="h-[5px] w-[64%] rounded-[9px]" style={{ background: c.line }} />
        <span
          className="mt-auto flex h-[18px] items-center justify-end rounded-[9px] px-[3px]"
          style={{ border: `1px solid ${c.line}` }}
        >
          <span className="size-[11px] rounded-full" style={{ background: c.accent }} />
        </span>
      </span>
    </>
  )
}

const OPTIONS: [ThemeChoice, string][] = [
  ['light', 'Light'],
  ['dark', 'Dark'],
  ['system', 'System'],
]

export function AppearancePage() {
  const { choice, setChoice } = useTheme()
  const mobile = useIsMobile()
  return (
    <>
      <div role="radiogroup" aria-label="Appearance" className="grid grid-cols-3 gap-4">
        {OPTIONS.map(([id, label]) => {
          const on = choice === id
          return (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setChoice(id)}
              className="flex flex-col gap-2.5 border-0 bg-transparent p-0 text-left text-text"
            >
              <span
                className="relative block w-full overflow-hidden rounded-[14px] transition-[box-shadow] duration-200"
                style={{ height: mobile ? 132 : 150, boxShadow: on ? '0 0 0 2px var(--accent)' : '0 0 0 1px var(--line)' }}
              >
                <span className="absolute inset-0 flex" style={{ background: (id === 'dark' ? TILE.dark : TILE.light).bg }}>
                  <Preview c={id === 'dark' ? TILE.dark : TILE.light} />
                </span>
                {id === 'system' && (
                  <span className="absolute inset-0 flex [clip-path:inset(0_0_0_50%)]" style={{ background: TILE.dark.bg }}>
                    <Preview c={TILE.dark} sidebar={false} />
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2 text-[15px]" style={{ fontWeight: on ? 500 : 400 }}>
                <span
                  className="flex size-[18px] items-center justify-center rounded-full"
                  style={{ border: `1.5px solid ${on ? 'var(--accent)' : 'var(--line)'}` }}
                >
                  <span className="size-2 rounded-full bg-accent" style={{ opacity: on ? 1 : 0 }} />
                </span>
                {label}
              </span>
            </button>
          )
        })}
      </div>
      <p className="m-0 text-sm text-muted">System follows your device's light and dark setting.</p>
    </>
  )
}
