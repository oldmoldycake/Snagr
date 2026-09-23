import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
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
          The agent reads this when picking which listings to track — condition, completeness,
          anything a human would check.
        </p>
      </div>

      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-1 text-xs text-ink-3 hover:text-ink-2">
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          <span className="shrink-0">Tracking options</span>
          <span className="ml-1 text-left text-ink-3/80">
            — {value.selectionMode === 'best_match' ? 'Best match' : 'Cheapest'} · up to{' '}
            {value.maxListings} listing{value.maxListings === 1 ? '' : 's'} ·{' '}
            {interval != null ? `every ${formatInterval(interval)} · ` : ''}
            {siteSummary}
            {value.hunt ? '' : ' · hunting off'}
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-3 space-y-3 rounded-sm border border-hairline bg-well p-3">
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
                    ? 'Ranks listings by how well they fit your criteria; price breaks ties. Poor matches are skipped even if slots are free.'
                    : 'Add criteria above so the agent has something to rank against.'
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
                <Label htmlFor="item-hunt">Hunting</Label>
                <p className="text-xs text-ink-3">
                  {value.hunt
                    ? 'Look for new listings on its own while slots are open.'
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
                          'rounded-sm border px-2 py-1 text-xs transition-colors',
                          selected
                            ? 'border-lume/50 bg-lume-glow text-lume'
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
