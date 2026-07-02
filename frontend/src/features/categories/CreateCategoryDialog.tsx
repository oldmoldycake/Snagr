import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { createCategory } from '@/api/endpoints'
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

export function CreateCategoryDialog({
  trigger,
  variant = 'primary',
  className,
}: {
  trigger: ReactNode
  variant?: 'primary' | 'ghost'
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const create = useMutation({
    mutationFn: () => createCategory({ name }),
    onSuccess: (category) => {
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      setOpen(false)
      setName('')
      navigate(`/categories/${category.slug}`)
    },
  })

  const fieldError =
    create.error instanceof ApiError ? (create.error.fields?.name ?? create.error.message) : null

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={variant} size="sm" className={className}>
          {trigger}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>New category</DialogTitle>
        <DialogDescription>
          A category groups the items you track and the sites the agent searches for them.
        </DialogDescription>
        <form
          className="mt-4"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          <Label htmlFor="category-name">Name</Label>
          <Input
            id="category-name"
            required
            autoFocus
            placeholder="GPUs, Keyboards, Home Lab…"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {fieldError ? <p className="mt-1.5 text-xs text-rise">{fieldError}</p> : null}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              Create category
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
