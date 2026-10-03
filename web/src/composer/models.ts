import type { Model, Models } from '@/api/types'

const PROVIDERS: Record<string, string> = { openrouter: 'OpenRouter', openai: 'OpenAI', custom: 'Custom' }

export const providerName = (p: string) => PROVIDERS[p] ?? p

/** The catalog grouped by provider, in catalog order. */
export function groupModels(models: Model[]): { provider: string; models: Model[] }[] {
  const groups: { provider: string; models: Model[] }[] = []
  for (const m of models) {
    const g = groups.find((x) => x.provider === m.provider)
    if (g) g.models.push(m)
    else groups.push({ provider: m.provider, models: [m] })
  }
  return groups
}

/** The model a new chat starts on: the user's default while it's available, else the server's
 *  default_model, else the first available one. */
export function initialModel(catalog: Models, userDefault: string | null): string | null {
  const ok = (id: string | null) => !!id && catalog.models.some((m) => m.id === id && m.available)
  if (ok(userDefault)) return userDefault
  if (ok(catalog.default_model)) return catalog.default_model
  return catalog.models.find((m) => m.available)?.id ?? null
}
