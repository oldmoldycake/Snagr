import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2, Trash2 } from 'lucide-react'
import { deleteCategory, listSites, setCategorySites, updateCategory } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Category } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/cn'

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
  const [siteIds, setSiteIds] = useState<number[]>(category.site_ids)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })

  const save = useMutation({
    mutationFn: async () => {
      if (name.trim() !== category.name) await updateCategory(category.id, { name: name.trim() })
      await setCategorySites(category.id, siteIds)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] })
      onOpenChange(false)
      const slug = name
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
      navigate(`/categories/${slug}`, { replace: true })
    },
  })

  const remove = useMutation({
    mutationFn: () => deleteCategory(category.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] })
      await queryClient.invalidateQueries({ queryKey: ['items'] })
      navigate('/', { replace: true })
    },
  })

  const toggleSite = (id: number) => {
    setSiteIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Edit category</DialogTitle>
        <DialogDescription>
          The agent searches this category's linked sites when it runs.
        </DialogDescription>

        <div className="mt-4 space-y-4">
          <div>
            <Label htmlFor="edit-category-name">Name</Label>
            <Input id="edit-category-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div>
            <Label>Linked sites</Label>
            {sites.data?.data.length === 0 ? (
              <p className="text-xs text-ink-3">No sites yet — add sites on the Sites page first.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {sites.data?.data.map((site) => {
                  const selected = siteIds.includes(site.id)
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

          <div className="border-t border-hairline pt-3">
            {confirmingDelete ? (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs text-rise">
                  Delete “{category.name}” and its {category.item_count} item
                  {category.item_count === 1 ? '' : 's'}? This cannot be undone.
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
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={save.isPending || !name.trim()} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
