import type { SelectionMode } from '@/api/types'

/** A form's selection mode, and whether it is Best match only because criteria were typed. */
export interface CriteriaMode {
  mode: SelectionMode
  switched: boolean
}

/**
 * The selection mode once the criteria go from `before` to `after`, while the
 * user hasn't picked a mode. Cheapest ranks by price alone, so typing criteria
 * into an empty field switches to Best match, which ranks by them; clearing
 * them undoes that switch. A mode that was already Best match is left alone.
 */
export function modeForCriteria(current: CriteriaMode, before: string, after: string): CriteriaMode {
  const had = before.trim() !== ''
  const has = after.trim() !== ''
  if (!had && has && current.mode === 'cheapest') return { mode: 'best_match', switched: true }
  if (current.switched && !has) return { mode: 'cheapest', switched: false }
  return current
}
