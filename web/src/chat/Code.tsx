import type { ReactNode } from 'react'
import { useTokens } from './highlight'

/** One line's text, syntax-colored once Shiki has the line's tokens (plain until then). */
export function CodeLine({ text, tokens }: { text: string; tokens: { content: string; color?: string }[] | undefined }) {
  if (!tokens) return <>{text || ' '}</>
  if (!tokens.length) return <>{' '}</>
  return (
    <>
      {tokens.map((t, i) => (
        <span key={i} style={{ color: t.color }}>
          {t.content}
        </span>
      ))}
    </>
  )
}

/** A fenced code block in Otto's prose. */
export function CodeBlock({ code, lang }: { code: string; lang: string | null }) {
  const tokens = useTokens(code, lang)
  const lines = code.split('\n')
  return (
    <pre className="my-3.5 overflow-x-auto rounded-xl bg-bg2 px-4 py-3.5 font-mono text-[13px] leading-[1.7]">
      {lines.map((l, i) => (
        <Line key={i}>
          <CodeLine text={l} tokens={tokens?.[i]} />
        </Line>
      ))}
    </pre>
  )
}

function Line({ children }: { children: ReactNode }) {
  return <div className="whitespace-pre">{children}</div>
}
