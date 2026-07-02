import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { updateItem } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { ItemSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TrackingFields, trackingPayload, type TrackingValue } from './TrackingFields'

export function EditItemDialog({
  item,
  open,
  onOpenChange,
}: {
  item: ItemSummary
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [name, setName] = useState(item.name)
  const [target, setTarget] = useState(item.target_price ?? '')
  const [tracking, setTracking] = useState<TrackingValue>({
    criteria: item.criteria ?? '',
    selectionMode: item.selection_mode,
    maxListings: item.max_listings,
    siteIds: item.site_ids,
  })
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: () =>
      updateItem(item.id, {
        name: name.trim(),
        target_price: String(target).trim() ? Number(target).toFixed(2) : null,
        ...trackingPayload(tracking),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      onOpenChange(false)
    },
  })

  const errorMessage = save.error instanceof ApiError ? save.error.message : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Edit item</DialogTitle>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          {errorMessage ? <p className="text-xs text-rise">{errorMessage}</p> : null}
          <div>
            <Label htmlFor="edit-item-name">Name</Label>
            <Input id="edit-item-name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="edit-item-target">Target price</Label>
            <div className="relative">
              <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 font-mono text-xs text-ink-3">
                $
              </span>
              <Input
                id="edit-item-target"
                type="number"
                step="0.01"
                min="0"
                className="pl-6 font-mono tnum"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </div>
          </div>

          <TrackingFields categoryId={item.category_id} value={tracking} onChange={setTracking} />

          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={save.isPending || !name.trim()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
