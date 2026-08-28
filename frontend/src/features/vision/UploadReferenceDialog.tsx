import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { uploadReference } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import type { ReferenceLabel } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented } from '@/components/ui/segmented'

const LABEL_OPTIONS = [
  { value: 'real', label: 'Real' },
  { value: 'fake', label: 'Fake' },
] as const

export function UploadReferenceDialog({
  itemId,
  open,
  onOpenChange,
}: {
  itemId: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [label, setLabel] = useState<ReferenceLabel>('real')
  const [variantTag, setVariantTag] = useState('')
  const queryClient = useQueryClient()

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.set('file', file!)
      form.set('label', label)
      if (variantTag.trim()) form.set('variant_tag', variantTag.trim())
      return uploadReference(itemId, form)
    },
    onSuccess: () => {
      toast.success(`Added to the ${label} references`)
      void queryClient.invalidateQueries({ queryKey: qk.itemReferences(itemId) })
      onOpenChange(false)
    },
  })

  const error = upload.error instanceof ApiError ? upload.error : null
  const fieldError = error?.fields?.file ?? error?.fields?.label

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Add reference photo</DialogTitle>
        <DialogDescription>
          A photo of a unit you know first-hand. Real references teach the check what genuine
          photos look like; fake references teach it what to condemn.
        </DialogDescription>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            upload.mutate()
          }}
        >
          {error ? <p className="text-xs text-rise">{fieldError ?? error.message}</p> : null}
          <div>
            <Label htmlFor="reference-file">Photo (max 10 MB)</Label>
            <Input
              id="reference-file"
              type="file"
              accept="image/*"
              required
              className="h-auto py-1.5 text-xs file:mr-2 file:rounded-sm file:border-0 file:bg-raised file:px-2 file:py-0.5 file:font-mono file:text-[11px] file:text-ink-2"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div>
            <Label>Label</Label>
            <Segmented options={LABEL_OPTIONS} value={label} onChange={setLabel} ariaLabel="Reference label" />
          </div>
          <div>
            <Label htmlFor="reference-variant">Variant tag (optional)</Label>
            <Input
              id="reference-variant"
              value={variantTag}
              onChange={(e) => setVariantTag(e.target.value)}
              placeholder="e.g. Player's Choice label"
            />
            <p className="mt-1.5 text-xs text-ink-3">
              Names a legitimate variant (alternate art, regional box) so its photos count as real
              instead of reading as suspicious.
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={upload.isPending || !file}>
              {upload.isPending ? <Loader2 className="animate-spin" /> : null}
              Upload
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
