import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { updateItem } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { ItemDetail, ItemSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useSession } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { currencySign } from '@/lib/money'
import { hasItemEdits, type ItemForm } from './itemEdits'
import { itemSaveErrors } from './itemSaveErrors'
import { renameNote } from './renameNote'
import { parseTargetPrice } from './targetPrice'
import { TrackingFields, trackingPayload, type TrackingValue } from './TrackingFields'

/**
 * Edit an item's name, target price and tracking options. Seeds its form from
 * props once — remount it (via key) to pick up server-side changes.
 */
export function EditItemDialog({
  item,
  open,
  onOpenChange,
  onSaved,
  focusTracking = false,
}: {
  item: ItemSummary
  open: boolean
  onOpenChange: (open: boolean) => void
  /** a rename of an item others watch too moves the watch, so `saved.id` can differ from `item.id` */
  onSaved?: (saved: ItemDetail) => void
  /** open on the tracking options, expanded and in view, rather than on the name */
  focusTracking?: boolean
}) {
  const [name, setName] = useState(item.name)
  const [target, setTarget] = useState(item.target_price ?? '')
  const [targetError, setTargetError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const targetRef = useRef<HTMLInputElement>(null)
  const sign = currencySign(item.currency)
  const isAdmin = useSession().data?.role === 'admin'
  const nameNote = renameNote(item.watcher_count, isAdmin)
  const [tracking, setTracking] = useState<TrackingValue>({
    criteria: item.criteria ?? '',
    selectionMode: item.selection_mode,
    maxListings: item.max_listings,
    recheckIntervalMinutes: item.recheck_interval_minutes,
    hunt: item.hunt,
    siteIds: item.site_ids,
  })
  // useState keeps its first value: the form as it opened, to tell edits from it
  const [opened] = useState<ItemForm>({ name, target, tracking })
  const bodyRef = useRef<HTMLDivElement>(null)
  const trackingToggleRef = useRef<HTMLButtonElement>(null)
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: (targetPrice: string | null) =>
      updateItem(item.id, {
        name: name.trim(),
        target_price: targetPrice,
        ...trackingPayload(tracking),
      }),
    meta: { inlineError: true },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      onOpenChange(false)
      onSaved?.(saved)
    },
    onError: (error) => {
      // bring a refused name or target into view, the way a mistyped target is
      const fields = error instanceof ApiError ? error.fields : undefined
      if (fields?.name) nameRef.current?.focus()
      else if (fields?.target_price) targetRef.current?.focus()
    },
  })

  const saveErrors = itemSaveErrors(save.error)
  const shownTargetError = targetError ?? saveErrors.fields.target_price
  const dirty = hasItemEdits(opened, { name, target, tracking })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        dirty={dirty}
        onOpenAutoFocus={(e) => {
          const body = bodyRef.current
          const toggle = trackingToggleRef.current
          if (!focusTracking || !body || !toggle) return
          e.preventDefault()
          toggle.focus({ preventScroll: true })
          // Bring the toggle to the top of the body, or as near as the body scrolls, so
          // the options below it are in view. Set by hand: scrollIntoView scrolls every
          // ancestor, and can slide the dialog's header out of sight.
          body.scrollTop += toggle.getBoundingClientRect().top - body.getBoundingClientRect().top
        }}
      >
        <DialogHeader>
          <DialogTitle>Edit item</DialogTitle>
        </DialogHeader>
        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            const parsed = parseTargetPrice(target, item.currency)
            if ('error' in parsed) {
              setTargetError(parsed.error)
              targetRef.current?.focus()
              return
            }
            save.mutate(parsed.price)
          }}
        >
          <DialogBody ref={bodyRef} className="space-y-3">
            {saveErrors.message ? (
              <p role="alert" className="text-xs text-rise">
                {saveErrors.message}
              </p>
            ) : null}
            <div>
              <Label htmlFor="edit-item-name">Name</Label>
              <Input
                ref={nameRef}
                id="edit-item-name"
                required
                aria-invalid={!!saveErrors.fields.name || undefined}
                className="aria-invalid:border-rise/60"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {saveErrors.fields.name ? (
                <p role="alert" className="mt-1.5 text-xs text-rise">
                  ⚠ {saveErrors.fields.name}
                </p>
              ) : null}
              {nameNote ? (
                <p className={cn('mt-1.5 text-xs', isAdmin ? 'text-warn' : 'text-ink-3')}>{nameNote}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="edit-item-target">Target price</Label>
              <div className="relative">
                <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 font-mono text-xs text-ink-3">
                  {sign}
                </span>
                <Input
                  ref={targetRef}
                  id="edit-item-target"
                  inputMode="decimal"
                  aria-invalid={!!shownTargetError || undefined}
                  className="font-mono tnum aria-invalid:border-rise/60"
                  // clears a sign of any length (CA$): the input's ch is wider than the sign's
                  style={{ paddingLeft: `calc(${sign.length}ch + 1rem)` }}
                  value={target}
                  onChange={(e) => {
                    setTarget(e.target.value)
                    setTargetError(null)
                  }}
                />
              </div>
              {shownTargetError ? (
                <p role="alert" className="mt-1.5 text-xs text-rise">
                  ⚠ {shownTargetError}
                </p>
              ) : null}
              <p className="mt-1.5 text-xs text-ink-3">
                {target.trim() ? (
                  <>
                    You'll see <span className="text-drop">⌖ at target</span> when the best price is at or below this.
                  </>
                ) : (
                  <>
                    Without a target, Snagr can't mark the item <span className="text-drop">⌖ at target</span> or
                    alert you when its price is low enough.
                  </>
                )}
              </p>
            </div>

            <TrackingFields
              categoryId={item.category_id}
              value={tracking}
              onChange={setTracking}
              defaultOpen={focusTracking}
              toggleRef={trackingToggleRef}
              intervalError={saveErrors.fields.recheck_interval_minutes}
            />
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={save.isPending || !name.trim()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
