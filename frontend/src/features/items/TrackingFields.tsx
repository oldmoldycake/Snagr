import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listCategories, listSites } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { SelectionMode } from '@/api/types'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented } from '@/components/ui/segmented'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useInstance } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { formatInterval } from '@/lib/time'

/** Form state for the tracking options; trackingPayload turns it into the API fields. */
export interface TrackingValue {
  criteria: string
  selectionMode: SelectionMode
  maxListings: number
  /** minutes between price checks; null = the instance default */
  recheckIntervalMinutes: number | null
  /** false = hunted only when someone presses Hunt now */
  hunt: boolean
  /** null = all of the category's sites */
  siteIds: number[] | null
}

/** Tracking options for a new item. */
export const DEFAULT_TRACKING: TrackingValue = {
  criteria: '',
  selectionMode: 'cheapest',
  maxListings: 5,
  recheckIntervalMinutes: null,
  hunt: true,
  siteIds: null,
}

const INTERVAL_PRESETS = [15, 30, 60, 360]
const INTERVAL_OPTIONS = [
  ...INTERVAL_PRESETS.map((m) => ({ value: String(m), label: formatInterval(m) })),
  { value: 'custom', label: 'Custom' },
]

/** The tracking fields of a create/update item request; blank criteria is sent as null. */
export function trackingPayload(value: TrackingValue) {
  return {
    criteria: value.criteria.trim() || null,
    selection_mode: value.selectionMode,
    max_listings: value.maxListings,
    recheck_interval_minutes: value.recheckIntervalMinutes,
    hunt: value.hunt,
    site_ids: value.siteIds,
  }
}

/**
 * Criteria textarea + collapsed "Tracking options" (mode, slots, hunting,
 * check interval, sites), shared by the add and edit item dialogs.
 */
export function TrackingFields({
  categoryId,
  value,
  onChange,
}: {
  categoryId: number
  value: TrackingValue
  onChange: (value: TrackingValue) => void
}) {
  const [open, setOpen] = useState(false)
  // once the user picks a mode explicitly, stop auto-switching it
  const modeTouched = useRef(false)
  // a stored interval that is not a preset opens on the custom field
  const [customInterval, setCustomInterval] = useState(
    value.recheckIntervalMinutes != null && !INTERVAL_PRESETS.includes(value.recheckIntervalMinutes),
  )
  const defaultInterval = useInstance().data?.recheck_interval_default

  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  const category = categories.data?.data.find((c) => c.id === categoryId)
  const categorySites = sites.data?.data.filter((s) => category?.site_ids.includes(s.id)) ?? []

  const effectiveSiteIds = value.siteIds ?? categorySites.map((s) => s.id)

  const setCriteria = (criteria: string) => {
    const next = { ...value, criteria }
    // typing criteria implies best-match ranking unless the user said otherwise
    if (!modeTouched.current && value.criteria.trim() === '' && criteria.trim() !== '') {
      next.selectionMode = 'best_match'
    }
    onChange(next)
  }

  const setMode = (selectionMode: SelectionMode) => {
    modeTouched.current = true
    onChange({ ...value, selectionMode })
  }

  const toggleSite = (id: number) => {
    const next = effectiveSiteIds.includes(id)
      ? effectiveSiteIds.filter((s) => s !== id)
      : [...effectiveSiteIds, id]
    // all (or none) selected = no restriction
    onChange({
      ...value,
      siteIds: next.length === 0 || next.length === categorySites.length ? null : next,
    })
  }

  const setIntervalChoice = (choice: string) => {
    if (choice === 'custom') {
      setCustomInterval(true)
      return
    }
    setCustomInterval(false)
    onChange({ ...value, recheckIntervalMinutes: Number(choice) })
  }

  const interval = value.recheckIntervalMinutes ?? defaultInterval

  const siteSummary =
    value.siteIds == null
      ? 'all sites'
      : value.siteIds.length <= 2
        ? categorySites
            .filter((s) => value.siteIds!.includes(s.id))
            .map((s) => s.name)
            .join(', ') || 'no sites'
        : `${value.siteIds.length} sites`

  return (
    <>
      <div>
        <Label htmlFor="item-criteria">What are you looking for? (optional)</Label>
        <Textarea
          id="item-criteria"
          placeholder="e.g. dry battery and damaged case preferred but not required — must be an authentic cartridge"
          value={value.criteria}
          onChange={(e) => setCriteria(e.target.value)}
        />
        <p className="mt-1.5 text-xs text-ink-3">
          Snagr reads this when choosing listings: condition, completeness, anything you'd check
          yourself.
        </p>
      </div>

      <Collapsible open={open} onOpenChange={setOpen} className="rounded-md border border-hairline-strong bg-well">
        <CollapsibleTrigger className="flex w-full items-center gap-2.5 px-3 py-[9px] text-left font-mono text-[11px] text-ink-2 focus-visible:-outline-offset-2">
          <span className="text-[10px] tracking-[0.14em] text-ink-3 uppercase">Tracking</span>
          <span className="min-w-0 flex-1 truncate">
            {value.selectionMode === 'best_match' ? 'Best match' : 'Cheapest'} · up to {value.maxListings} ·{' '}
            {interval != null ? `every ${formatInterval(interval)} · ` : ''}
            {siteSummary}
            {value.hunt ? '' : ' · hunting off'}
          </span>
          <svg
            viewBox="0 0 10 10"
            aria-hidden
            className={cn('size-3 shrink-0 transition-transform duration-[180ms] ease-shelf', open && 'rotate-90')}
          >
            <path d="M3.5 1.5 7 5l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-3 border-t border-hairline p-3">
            <div>
              <Label>How to pick listings</Label>
              <Segmented
                options={[
                  { value: 'cheapest', label: 'Cheapest' },
                  { value: 'best_match', label: 'Best match' },
                ]}
                value={value.selectionMode}
                onChange={setMode}
                ariaLabel="Selection mode"
              />
              <p className="mt-1.5 text-xs text-ink-3">
                {value.selectionMode === 'best_match'
                  ? value.criteria.trim()
                    ? "Ranks listings by how well they fit your criteria; price breaks ties. Poor matches are skipped even when there's room for more listings."
                    : 'Add criteria above so Snagr has something to rank against.'
                  : 'Tracks the lowest-priced listings, criteria ignored for selection.'}
              </p>
            </div>

            <div>
              <Label htmlFor="item-max-listings">Track up to</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="item-max-listings"
                  type="number"
                  min={1}
                  max={10}
                  className="w-16 font-mono tnum"
                  value={value.maxListings}
                  onChange={(e) => {
                    const n = Math.round(Number(e.target.value))
                    onChange({ ...value, maxListings: Number.isFinite(n) ? Math.min(10, Math.max(1, n)) : 5 })
                  }}
                />
                <span className="text-xs text-ink-3">listings at once</span>
              </div>
            </div>

            <div className="flex items-start justify-between gap-3">
              <div>
                <Label htmlFor="item-hunt">Hunt automatically</Label>
                <p className="text-xs text-ink-3">
                  {value.hunt
                    ? "Search for new listings on its own whenever there's room for more."
                    : 'Only when you press Hunt now. Prices are still checked.'}
                </p>
              </div>
              <Switch
                id="item-hunt"
                className="mt-0.5"
                checked={value.hunt}
                onCheckedChange={(hunt) => onChange({ ...value, hunt })}
              />
            </div>

            <div>
              <Label>Check every</Label>
              <Segmented
                options={INTERVAL_OPTIONS}
                value={
                  customInterval
                    ? 'custom'
                    : value.recheckIntervalMinutes != null
                      ? String(value.recheckIntervalMinutes)
                      : null
                }
                onChange={setIntervalChoice}
                ariaLabel="Check interval"
              />
              {customInterval ? (
                <div className="mt-2 flex items-center gap-2">
                  <Input
                    id="item-recheck-interval"
                    type="number"
                    min={1}
                    max={1440}
                    step={1}
                    aria-label="Check interval in minutes"
                    placeholder={defaultInterval != null ? String(defaultInterval) : undefined}
                    className="w-20 font-mono tnum"
                    value={value.recheckIntervalMinutes ?? ''}
                    onChange={(e) => {
                      // kept as typed, not rounded: a fractional value fails the
                      // input's step and the browser refuses to submit the form
                      const n = Number(e.target.value)
                      onChange({
                        ...value,
                        recheckIntervalMinutes: e.target.value.trim() && Number.isFinite(n) ? n : null,
                      })
                    }}
                  />
                  <span className="text-xs text-ink-3">minutes</span>
                </div>
              ) : null}
              <p className="mt-1.5 text-xs text-ink-3">
                {value.recheckIntervalMinutes == null ? (
                  defaultInterval != null ? (
                    `Every ${formatInterval(defaultInterval)} — this instance's default.`
                  ) : null
                ) : (
                  <>
                    How often each tracked listing's price is re-read.{' '}
                    <button
                      type="button"
                      className="text-lume hover:underline"
                      onClick={() => {
                        setCustomInterval(false)
                        onChange({ ...value, recheckIntervalMinutes: null })
                      }}
                    >
                      Use the default
                      {defaultInterval != null ? ` (${formatInterval(defaultInterval)})` : ''}
                    </button>
                  </>
                )}
              </p>
            </div>

            <div>
              <Label>Search these sites</Label>
              {categorySites.length === 0 ? (
                <p className="text-xs text-warn">
                  This category has no linked sites yet — edit the category to link some.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {categorySites.map((site) => {
                    const selected = effectiveSiteIds.includes(site.id)
                    return (
                      <button
                        key={site.id}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => toggleSite(site.id)}
                        className={cn(
                          'relative rounded-sm border px-2 py-1 text-xs transition-colors focus-visible:-outline-offset-2',
                          // Segmented's plate, one per picked site: its lume bar grows from the middle
                          'after:absolute after:inset-x-1.5 after:bottom-0.5 after:h-0.5 after:scale-x-0 after:rounded-[1px] after:bg-lume after:transition-transform after:duration-150 after:ease-shelf aria-pressed:after:scale-x-100',
                          selected
                            ? 'border-hairline-strong bg-raised text-ink'
                            : 'border-hairline text-ink-3 hover:text-ink-2',
                        )}
                      >
                        {site.name}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </>
  )
}
