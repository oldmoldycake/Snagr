import { useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'
import { createItem, listCategories, listSites } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ItemSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogEyebrow,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { siteList } from '@/features/sites/siteList'
import { DEFAULT_TRACKING, TrackingFields, trackingPayload, type TrackingValue } from './TrackingFields'

/** Add an item to one category, whose sites the hunter then searches for it. */
export function AddItemDialog({
  categoryId,
  categoryName,
  trigger,
  variant = 'primary',
  className,
  label,
  onAdded,
}: {
  categoryId: number
  categoryName: string
  trigger?: ReactNode
  variant?: 'primary' | 'default'
  className?: string
  /** accessible name for the trigger, when its visible text alone doesn't name the category */
  label?: string
  onAdded?: (item: ItemSummary) => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [nameMissing, setNameMissing] = useState(false)
  const [target, setTarget] = useState('')
  const [tracking, setTracking] = useState<TrackingValue>(DEFAULT_TRACKING)
  const nameRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories, enabled: open })
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites, enabled: open })
  const siteIds = categories.data?.data.find((c) => c.id === categoryId)?.site_ids ?? []
  const siteNames = (sites.data?.data ?? []).filter((s) => siteIds.includes(s.id)).map((s) => s.name)

  const create = useMutation({
    mutationFn: () =>
      createItem({
        category_id: categoryId,
        name: name.trim(),
        target_price: target.trim() ? Number(target).toFixed(2) : null,
        ...trackingPayload(tracking),
      }),
    onSuccess: (item) => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      setOpen(false)
      onAdded?.(item)
    },
  })

  const errorMessage = create.error instanceof ApiError ? create.error.message : null
  const dirty = name.trim() !== '' || target.trim() !== '' || tracking.criteria.trim() !== ''

  // Reset when opening rather than closing, so the exit animation shows the dialog as it was.
  const onOpenChange = (next: boolean) => {
    if (next) {
      setName('')
      setNameMissing(false)
      setTarget('')
      setTracking(DEFAULT_TRACKING)
      create.reset()
    }
    setOpen(next)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant={variant} size="sm" className={className} aria-label={label}>
          {trigger ?? (
            <>
              <Plus /> Add item
            </>
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-[520px]" onInteractOutside={(e) => dirty && e.preventDefault()}>
        <DialogHeader>
          <DialogEyebrow>Add item</DialogEyebrow>
          <DialogTitle>{categoryName}</DialogTitle>
          <DialogDescription>
            Snagr searches{' '}
            {siteNames.length > 0 ? (
              <b className="font-medium text-ink">{siteList(siteNames)}</b>
            ) : (
              "this category's sites"
            )}{' '}
            for listings. You don't need to paste any links.
          </DialogDescription>
        </DialogHeader>
        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) {
              setNameMissing(true)
              nameRef.current?.focus()
              return
            }
            create.mutate()
          }}
        >
          <DialogBody className="space-y-3">
            {errorMessage ? (
              <p role="alert" className="text-xs text-rise">
                {errorMessage}
              </p>
            ) : null}
            <div>
              <Label htmlFor="item-name">Item name</Label>
              <Input
                ref={nameRef}
                id="item-name"
                autoFocus
                autoComplete="off"
                placeholder="e.g. Pokémon Sapphire (GBA)"
                aria-invalid={nameMissing || undefined}
                className="aria-invalid:border-rise/60"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setNameMissing(false)
                }}
              />
              {nameMissing ? (
                <p role="alert" className="mt-1.5 text-xs text-rise">
                  ⚠ Give it a name.
                </p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="item-target">Target price (optional)</Label>
              <div className="relative">
                <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 font-mono text-xs text-ink-3">
                  $
                </span>
                <Input
                  id="item-target"
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="120.00"
                  className="pl-6 font-mono tnum"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                />
              </div>
              <p className="mt-1.5 text-xs text-ink-3">
                You'll see <span className="text-drop">⌖ at target</span> when the best price is at or below this.
              </p>
            </div>

            <TrackingFields categoryId={categoryId} value={tracking} onChange={setTracking} />
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              Add item
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
