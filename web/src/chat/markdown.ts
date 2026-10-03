/** Light markdown for Otto's replies: paragraphs, lists, headings, fenced code, and inline code,
 *  bold, italics and http(s) links. Parsed to a small tree that renders as React elements, so no
 *  HTML from the model ever reaches the page. */

export type Inline =
  | { t: 'text'; v: string }
  | { t: 'code'; v: string }
  | { t: 'strong'; c: Inline[] }
  | { t: 'em'; c: Inline[] }
  | { t: 'link'; href: string; c: Inline[] }

export type Block =
  | { t: 'p'; c: Inline[] }
  | { t: 'h'; c: Inline[] }
  | { t: 'ul' | 'ol'; items: Inline[][] }
  | { t: 'pre'; lang: string | null; code: string }

const INLINE = /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)|\*\*([^*]+?)\*\*|__([^_]+?)__|\*([^*\s][^*]*?)\*|(?<![\w])_([^_\s][^_]*?)_(?![\w])|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g

export function parseInline(s: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  for (const m of s.matchAll(INLINE)) {
    if (m.index > last) out.push({ t: 'text', v: s.slice(last, m.index) })
    if (m[1]) out.push({ t: 'code', v: m[2]!.trim() || m[2]! })
    else if (m[3] ?? m[4]) out.push({ t: 'strong', c: parseInline((m[3] ?? m[4])!) })
    else if (m[5] ?? m[6]) out.push({ t: 'em', c: parseInline((m[5] ?? m[6])!) })
    else if (m[7]) out.push({ t: 'link', href: m[8]!, c: parseInline(m[7]) })
    last = m.index + m[0].length
  }
  if (last < s.length) out.push({ t: 'text', v: s.slice(last) })
  return out
}

const UL = /^\s*[-*+]\s+(.*)$/
const OL = /^\s*\d+[.)]\s+(.*)$/
const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/
const HEADING = /^#{1,6}\s+(.*)$/

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ t: 'p', c: parseInline(para.join('\n')) })
    para = []
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!
    const fence = FENCE.exec(line)
    if (fence) {
      flush()
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i]!.trim().startsWith(fence[1]!)) code.push(lines[i++]!)
      blocks.push({ t: 'pre', lang: fence[2] || null, code: code.join('\n') })
      continue
    }
    if (!line.trim()) {
      flush()
      continue
    }
    const h = HEADING.exec(line)
    if (h) {
      flush()
      blocks.push({ t: 'h', c: parseInline(h[1]!) })
      continue
    }
    const list = UL.exec(line) ? 'ul' : OL.exec(line) ? 'ol' : null
    if (list) {
      flush()
      const re = list === 'ul' ? UL : OL
      const items: Inline[][] = []
      while (i < lines.length && re.test(lines[i]!)) items.push(parseInline(re.exec(lines[i++]!)![1]!))
      i--
      blocks.push({ t: list, items })
      continue
    }
    para.push(line)
  }
  flush()
  return blocks
}
