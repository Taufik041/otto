import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apply, readChoice, resolve, saveChoice, systemDark, watchSystem, type Theme, type ThemeChoice } from './theme'

type ThemeState = { choice: ThemeChoice; theme: Theme; setChoice: (c: ThemeChoice) => void }

const ThemeContext = createContext<ThemeState | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice)
  const [dark, setDark] = useState(systemDark)
  const theme = resolve(choice, dark)

  useEffect(() => watchSystem(setDark), [])
  useEffect(() => apply(theme), [theme])

  const value = useMemo<ThemeState>(
    () => ({
      choice,
      theme,
      setChoice: (c) => {
        saveChoice(c)
        setChoiceState(c)
      },
    }),
    [choice, theme],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme outside ThemeProvider')
  return ctx
}
