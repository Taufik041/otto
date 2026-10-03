/** A unified diff (as the runner's fs.replace/fs.write results carry it) → numbered rows. */
export type DiffRow =
  | { type: 'hunk'; text: string }
  | { type: 'ctx' | 'add' | 'del'; old: number | null; new: number | null; text: string }
  | { type: 'note'; text: string }

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/

export function parseDiff(diff: string): DiffRow[] {
  const rows: DiffRow[] = []
  let oldN = 0
  let newN = 0
  for (const line of diff.split('\n')) {
    if (line.startsWith('--- ') || line.startsWith('+++ ')) continue
    const h = HUNK.exec(line)
    if (h) {
      oldN = Number(h[1])
      newN = Number(h[2])
      rows.push({ type: 'hunk', text: line })
      continue
    }
    if (line.startsWith('\\')) {
      rows.push({ type: 'note', text: line.slice(2) })
      continue
    }
    if (line.startsWith('+')) rows.push({ type: 'add', old: null, new: newN++, text: line.slice(1) })
    else if (line.startsWith('-')) rows.push({ type: 'del', old: oldN++, new: null, text: line.slice(1) })
    else if (line.startsWith(' ')) rows.push({ type: 'ctx', old: oldN++, new: newN++, text: line.slice(1) })
  }
  return rows
}

// file extension → Shiki language id; highlight.ts loads exactly these grammars
const EXT: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx', mjs: 'javascript', cjs: 'javascript',
  json: 'json', md: 'markdown', css: 'css', scss: 'scss', html: 'html', yml: 'yaml', yaml: 'yaml', toml: 'toml',
  sh: 'shellscript', bash: 'shellscript', go: 'go', rs: 'rust', rb: 'ruby', java: 'java', kt: 'kotlin',
  swift: 'swift', c: 'c', h: 'c', cpp: 'cpp', cs: 'csharp', php: 'php', sql: 'sql', vue: 'vue', svelte: 'svelte',
  ini: 'ini', xml: 'xml',
}

/** "src/x.py" → a Shiki language id, or null for plain text. */
export function languageOf(path: string): string | null {
  const ext = path.split('/').pop()!.split('.').pop()!.toLowerCase()
  const name = path.split('/').pop()!.toLowerCase()
  if (name === 'dockerfile') return 'docker'
  if (name === 'makefile') return 'make'
  return EXT[ext] ?? null
}
