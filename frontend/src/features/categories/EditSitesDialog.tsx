import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { setCategorySites } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { Category } from '@/api/types'
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
} from '@/components/ui/dialog'
import { SitePicker } from '@/features/sites/SitePicker'

/**
 * Choose the sites a category searches. Seeds its selection from props once —
 * remount it (via key) each time it opens.
 */
export function EditSitesDialog({
  category,
  open,
  onOpenChange,
}: {
  category: Category
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [siteIds, setSiteIds] = useState<number[]>(category.site_ids)
  const [sitesMissing, setSitesMissing] = useState(false)
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: () => setCategorySites(category.id, siteIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      onOpenChange(false)
    },
  })

  const errorMessage = save.error instanceof ApiError ? save.error.message : null
  const changed = [...siteIds].sort().join() !== [...category.site_ids].sort().join()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent onInteractOutside={(e) => changed && e.preventDefault()}>
        <DialogHeader>
          <DialogEyebrow>Sites</DialogEyebrow>
          <DialogTitle>{category.name}</DialogTitle>
          <DialogDescription>The hunter searches these for every item on {category.name}.</DialogDescription>
        </DialogHeader>
        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            if (siteIds.length === 0) {
              setSitesMissing(true)
              return
            }
            save.mutate()
          }}
        >
          <DialogBody>
            <SitePicker
              selected={siteIds}
              onChange={(ids) => {
                setSiteIds(ids)
                if (ids.length > 0) setSitesMissing(false)
              }}
            />
            {sitesMissing ? (
              <p role="alert" className="mt-2.5 text-xs text-rise">
                ⚠ Pick at least one site. The hunter needs somewhere to look.
              </p>
            ) : null}
            {errorMessage ? (
              <p role="alert" className="mt-2.5 text-xs text-rise">
                {errorMessage}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save sites
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
