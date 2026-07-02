import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'
import { createItem } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DEFAULT_TRACKING, TrackingFields, trackingPayload, type TrackingValue } from './TrackingFields'

export function AddItemDialog({
  categoryId,
  categoryName,
  trigger,
}: {
  categoryId: number
  categoryName: string
  trigger?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [tracking, setTracking] = useState<TrackingValue>(DEFAULT_TRACKING)
  const queryClient = useQueryClient()

  const create = useMutation({
    mutationFn: () =>
      createItem({
        category_id: categoryId,
        name: name.trim(),
        target_price: target.trim() ? Number(target).toFixed(2) : null,
        ...trackingPayload(tracking),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      setOpen(false)
      setName('')
      setTarget('')
      setTracking(DEFAULT_TRACKING)
    },
  })

  const errorMessage = create.error instanceof ApiError ? create.error.message : null

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          {trigger ?? (
            <>
              <Plus /> Add item
            </>
          )}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Add item to {categoryName}</DialogTitle>
        <DialogDescription>
          The agent searches this category's sites for listings on its next run — no URLs needed.
        </DialogDescription>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          {errorMessage ? <p className="text-xs text-rise">{errorMessage}</p> : null}
          <div>
            <Label htmlFor="item-name">Item name</Label>
            <Input
              id="item-name"
              required
              autoFocus
              placeholder="Pokemon Emerald (GBA)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
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
              You'll see a <span className="text-drop">⌖ Snagged</span> badge when the best price hits this.
            </p>
          </div>

          <TrackingFields categoryId={categoryId} value={tracking} onChange={setTracking} />

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              Add item
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
