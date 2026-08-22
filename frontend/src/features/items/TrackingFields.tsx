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
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/cn'

export interface TrackingValue {
  criteria: string
  selectionMode: SelectionMode
  maxListings: number
  /** null = all of the category's sites */
  siteIds: number[] | null
}

export const DEFAULT_TRACKING: TrackingValue = {
  criteria: '',
  selectionMode: 'cheapest',
  maxListings: 5,
  siteIds: null,
}

/** Compose the ItemCreate/Update payload fields from the form value. */
export function trackingPayload(value: TrackingValue) {
  return {
    criteria: value.criteria.trim() || null,
    selection_mode: value.selectionMode,
    max_listings: value.maxListings,
    site_ids: value.siteIds,
  }
}

/**
 * Criteria textarea + collapsed "Tracking options" (mode, slots, sites),
 * shared by the add and edit item dialogs.
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
          Tracking options
          <span className="ml-1 text-ink-3/80">
            — {value.selectionMode === 'best_match' ? 'Best match' : 'Cheapest'} · up to{' '}
            {value.maxListings} listing{value.maxListings === 1 ? '' : 's'} · {siteSummary}
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
