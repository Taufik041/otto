import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apply, readChoice, resolve, saveChoice, systemDark, watchSystem, type Theme, type ThemeChoice } from './theme'

type ThemeState = { choice: ThemeChoice; theme: Theme; setChoice: (c: ThemeChoice) => void }

const ThemeContext = createContext<ThemeState | null>(null)

/** `fixed`: always this choice, never stored (the landing page follows the system, with no switch). */
export function ThemeProvider({ children, fixed }: { children: ReactNode; fixed?: ThemeChoice }) {
  const [stored, setChoiceState] = useState<ThemeChoice>(readChoice)
  const choice = fixed ?? stored
  const [dark, setDark] = useState(systemDark)
  const theme = resolve(choice, dark)

  useEffect(() => watchSystem(setDark), [])
  useEffect(() => apply(theme), [theme])

  const value = useMemo<ThemeState>(
    () => ({
      choice,
      theme,
      setChoice: (c) => {
        if (fixed) return
        saveChoice(c)
        setChoiceState(c)
      },
    }),
    [choice, theme, fixed],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme outside ThemeProvider')
  return ctx
}
