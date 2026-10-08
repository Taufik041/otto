import type { Model, Models } from '@/api/types'

/** The picker's groups: the default model first (no heading), then "Other models", in catalog order. */
export function groupModels(models: Model[], defaultId: string | null): { label: string; heading: boolean; models: Model[] }[] {
  const first = models.filter((m) => m.id === defaultId)
  const rest = models.filter((m) => m.id !== defaultId)
  return [
    ...(first.length ? [{ label: 'Default model', heading: false, models: first }] : []),
    ...(rest.length ? [{ label: 'Other models', heading: first.length > 0, models: rest }] : []),
  ]
}

/** The model a new chat starts on: the user's default while it's available, else the server's
 *  default_model, else the first available one. */
export function initialModel(catalog: Models, userDefault: string | null): string | null {
  const ok = (id: string | null) => !!id && catalog.models.some((m) => m.id === id && m.available)
  if (ok(userDefault)) return userDefault
  if (ok(catalog.default_model)) return catalog.default_model
  return catalog.models.find((m) => m.available)?.id ?? null
}
