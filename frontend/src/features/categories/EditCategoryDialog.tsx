import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2, Trash2 } from 'lucide-react'
import { deleteCategory, setCategorySites, updateCategory } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { Category } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SitePicker } from '@/features/sites/SitePicker'
import { hasCategoryEdits } from './categoryEdits'

/**
 * Rename a category, choose which sites it searches, or delete it. Seeds its
 * name from props once — remount it (via key) each time it opens. Saving stays
 * on the page it was opened from, since a rename keeps the slug; deleting goes
 * to the dashboard.
 */
export function EditCategoryDialog({
  category,
  open,
  onOpenChange,
}: {
  category: Category
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState(category.name)
  // Null until the picker is used: until then it shows the category's current
  // links and saving leaves them alone, so a rename can't undo sites linked
  // since the dialog opened.
  const [pickedSiteIds, setPickedSiteIds] = useState<number[] | null>(null)
  const siteIds = pickedSiteIds ?? category.site_ids
  const [sitesMissing, setSitesMissing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const save = useMutation({
    mutationFn: async () => {
      if (name.trim() !== category.name) await updateCategory(category.id, { name: name.trim() })
      if (pickedSiteIds) await setCategorySites(category.id, pickedSiteIds)
    },
    meta: { inlineError: true },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] })
      // item rows carry the category's name
      await queryClient.invalidateQueries({ queryKey: ['items'] })
      onOpenChange(false)
    },
  })

  // a blank or taken name is refused with the reason on `fields.name`
  const nameError = save.error instanceof ApiError ? (save.error.fields?.name ?? save.error.message) : null
  const changed = hasCategoryEdits(category, name, pickedSiteIds)

  const remove = useMutation({
    mutationFn: () => deleteCategory(category.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] })
      await queryClient.invalidateQueries({ queryKey: ['items'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      navigate('/', { replace: true })
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* with unsaved edits, Escape and clicks outside do nothing: only Cancel or ✕ throws them away */}
      <DialogContent
        onEscapeKeyDown={(e) => changed && e.preventDefault()}
        onInteractOutside={(e) => changed && e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Edit category</DialogTitle>
          <DialogDescription>
            Snagr searches this category's linked sites.
          </DialogDescription>
        </DialogHeader>

        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            // only a selection emptied here is refused: an untouched picker
            // leaves the links as they are, even when there are none
            if (pickedSiteIds?.length === 0) {
              setSitesMissing(true)
              return
            }
            save.mutate()
          }}
        >
          <DialogBody className="space-y-4">
            <div>
              <Label htmlFor="edit-category-name">Name</Label>
              <Input id="edit-category-name" value={name} onChange={(e) => setName(e.target.value)} />
              {nameError ? (
                <p role="alert" className="mt-1.5 text-xs text-rise">
                  {nameError}
                </p>
              ) : null}
            </div>

            <div>
              <SitePicker
                selected={siteIds}
                onChange={(ids) => {
                  setPickedSiteIds(ids)
                  if (ids.length > 0) setSitesMissing(false)
                }}
              />
              {sitesMissing ? (
                <p role="alert" className="mt-2.5 text-xs text-rise">
                  ⚠ Pick at least one site. Snagr needs somewhere to look.
                </p>
              ) : null}
            </div>

            <div className="border-t border-hairline pt-3">
              {confirmingDelete ? (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs text-rise">
                    Delete “{category.name}” and every item in it, yours and everyone else's? This cannot be
                    undone.
                  </p>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate()}
                  >
                    {remove.isPending ? <Loader2 className="animate-spin" /> : null}
                    Delete
                  </Button>
                </div>
              ) : (
                <Button variant="ghost" size="sm" className="text-rise" onClick={() => setConfirmingDelete(true)}>
                  <Trash2 /> Delete category
                </Button>
              )}
            </div>
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              className="max-sm:flex-[2]"
              disabled={save.isPending || !name.trim()}
            >
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
