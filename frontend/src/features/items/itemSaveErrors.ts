import { ApiError } from '@/api/client'

/** The fields of an item save that the add and edit dialogs show an error beside. */
const FIELDS_SHOWN = ['name', 'target_price', 'recheck_interval_minutes']

/**
 * A refused item save, split the way the add and edit dialogs show it: the
 * errors the server tied to fields go beside those fields, and its message goes
 * at the top unless every field it named is one the dialogs show, so nothing
 * is said twice or left unsaid.
 */
export function itemSaveErrors(error: unknown): { fields: Partial<Record<string, string>>; message: string | null } {
  if (!(error instanceof ApiError)) return { fields: {}, message: null }
  const fields = error.fields ?? {}
  const named = Object.keys(fields)
  const placed = named.length > 0 && named.every((field) => FIELDS_SHOWN.includes(field))
  return { fields, message: placed ? null : error.message }
}
