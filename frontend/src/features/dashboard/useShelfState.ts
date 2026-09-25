import { useCallback, useEffect, useState } from 'react'
import type { StoredShelf } from './shelves'

type Stored = Map<number, StoredShelf>

// Collapse state is a per-browser convenience, so storage failures (private
// mode, a full or blocked quota, a hand-edited value) are ignored rather than
// surfaced: the dashboard falls back to its defaults.
function read(key: string | null): Stored {
  if (key == null) return new Map()
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw) as Record<string, StoredShelf>
    const map: Stored = new Map()
    for (const [id, entry] of Object.entries(parsed)) {
      if (typeof entry?.collapsed === 'boolean' && typeof entry.snaggedAt === 'number') map.set(Number(id), entry)
    }
    return map
  } catch {
    return new Map()
  }
}

function persist(key: string, map: Stored) {
  try {
    localStorage.setItem(key, JSON.stringify(Object.fromEntries(map)))
  } catch {
    // see read()
  }
}

/**
 * Which shelves this browser has collapsed, for one user
 * (`snagr:shelves:<user id>`). A null user id (signed out, or a search is
 * showing) reads and writes nothing. `write` merges entries and drops ids not
 * in `liveIds`, so deleted categories don't linger.
 */
export function useShelfState(userId: number | null) {
  const key = userId == null ? null : `snagr:shelves:${userId}`
  const [state, setState] = useState(() => ({ key, stored: read(key), dirty: false }))
  // another user, or a search starting or ending: re-read during render rather
  // than showing a frame of the previous key's state
  if (state.key !== key) setState({ key, stored: read(key), dirty: false })

  useEffect(() => {
    if (state.dirty && state.key != null) persist(state.key, state.stored)
  }, [state])

  const write = useCallback((entries: Stored, liveIds: Set<number>) => {
    setState((prev) => {
      if (prev.key == null) return prev
      const stored: Stored = new Map([...prev.stored].filter(([id]) => liveIds.has(id)))
      for (const [id, entry] of entries) stored.set(id, entry)
      return { ...prev, stored, dirty: true }
    })
  }, [])

  return { stored: state.stored, write }
}
