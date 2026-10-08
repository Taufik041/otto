import type { ReactNode } from 'react'
import { CodeBlock } from './Code'
import { parseMarkdown, type Inline } from './markdown'

function inline(nodes: Inline[]): ReactNode[] {
  return nodes.map((n, i) => {
    switch (n.t) {
      case 'text':
        return n.v
      case 'code':
        return (
          <code key={i} className="rounded-md bg-tag px-1.5 py-px font-mono text-[.86em]">
            {n.v}
          </code>
        )
      case 'strong':
        return <strong key={i} className="font-semibold">{inline(n.c)}</strong>
      case 'em':
        return <em key={i}>{inline(n.c)}</em>
      case 'link':
        return (
          <a key={i} href={n.href} target="_blank" rel="noopener noreferrer">
            {inline(n.c)}
          </a>
        )
    }
  })
}

/** Otto's prose: 16px, 1.65 line height, paragraphs 12px apart, as in the design. */
export function Markdown({ text, className = 'text-base leading-[1.65]' }: { text: string; className?: string }) {
  const blocks = parseMarkdown(text)
  return (
    <div className={`${className} text-pretty [&>*:first-child]:mt-0 [&>*:last-child]:mb-0`}>
      {blocks.map((b, i) => {
        switch (b.t) {
          case 'p':
            return <p key={i} className="mb-0 mt-3 whitespace-pre-wrap">{inline(b.c)}</p>
          case 'h':
            return <p key={i} className="mb-0 mt-4 font-medium">{inline(b.c)}</p>
          case 'ul':
          case 'ol': {
            const List = b.t
            return (
              <List key={i} className={`mb-0 mt-3 pl-6 ${b.t === 'ul' ? 'list-disc' : 'list-decimal'}`}>
                {b.items.map((item, j) => (
                  <li key={j} className="mt-1">{inline(item)}</li>
                ))}
              </List>
            )
          }
          case 'pre':
            return <CodeBlock key={i} code={b.code} lang={b.lang} />
        }
      })}
    </div>
  )
}
