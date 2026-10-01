/** "updated 2h ago", as in the design. */
export function updatedAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return ''
  const s = Math.max(0, (now.getTime() - Date.parse(iso)) / 1000)
  if (s < 60) return 'updated just now'
  const m = s / 60
  if (m < 60) return `updated ${Math.floor(m)}m ago`
  const h = m / 60
  if (h < 24) return `updated ${Math.floor(h)}h ago`
  const d = h / 24
  if (d < 7) return `updated ${Math.floor(d)}d ago`
  if (d < 30) return `updated ${Math.floor(d / 7)}w ago`
  if (d < 365) return `updated ${Math.floor(d / 30)}mo ago`
  return `updated ${Math.floor(d / 365)}y ago`
}

export const number = (n: number) => n.toLocaleString('en-US')

/** 412k, 1.2M */
export function compact(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${n < 10_000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') : Math.round(n / 1000)}k`
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
}

export function usd(n: number): string {
  return `≈ $${n < 0.01 && n > 0 ? n.toFixed(4) : n.toFixed(2)}`
}

/** "TK" for "Taufik Khan"; the email's first letter when there's no name. */
export function initials(name: string | null | undefined, email?: string | null): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0]![0]! + words[words.length - 1]![0]!).toUpperCase()
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase()
  return (email?.[0] ?? '?').toUpperCase()
}

export function firstName(name: string | null | undefined): string {
  return (name ?? '').trim().split(/\s+/)[0] ?? ''
}

/** "Sep 16" */
export function shortDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y!, m! - 1, d!).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
