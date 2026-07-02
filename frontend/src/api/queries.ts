import type { TimeRange } from '@/lib/time'
import type { ItemListParams, RunListParams } from './types'

/**
 * Query key factory. Invalidation relies on prefix matching:
 * invalidating ['items'] hits every item list, detail, and chart query.
 */
export const qk = {
  session: ['session'] as const,
  instance: ['instance'] as const,

  categories: ['categories'] as const,
  category: (id: number) => ['categories', id] as const,
  categoryChange: (id: number, range: TimeRange) => ['categories', id, 'change', range] as const,

  sites: ['sites'] as const,

  items: (params: ItemListParams = {}) => ['items', 'list', params] as const,
  item: (id: number) => ['items', 'detail', id] as const,
  itemHistory: (id: number, range: TimeRange) => ['items', 'detail', id, 'history', range] as const,
  itemSummary: (id: number, range: TimeRange) => ['items', 'detail', id, 'summary', range] as const,
  itemChecks: (id: number) => ['items', 'detail', id, 'checks'] as const,

  dashboard: (range: TimeRange) => ['dashboard', range] as const,
  dashboardDrops: (range: TimeRange) => ['dashboard', range, 'drops'] as const,

  runs: (params: RunListParams = {}) => ['runs', 'list', params] as const,
  run: (id: number) => ['runs', 'detail', id] as const,
  runEvents: (id: number) => ['runs', 'detail', id, 'events'] as const,

  adminUsers: ['admin', 'users'] as const,
  adminInvites: ['admin', 'invites'] as const,
}
