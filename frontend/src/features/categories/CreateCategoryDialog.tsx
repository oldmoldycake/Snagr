import { useRef, useState, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { createCategory, setCategorySites } from '@/api/endpoints'
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
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { StepPips } from '@/components/ui/step-pips'
import { SitePicker } from '@/features/sites/SitePicker'

const SUGGESTIONS = ['Keyboards', 'Retro games', 'Camera lenses', 'Home lab']

/**
 * Two-step New category dialog behind the given trigger: a name, then the sites
 * the hunter searches. With `onCreated` it hands over the new category and stays
 * on the page; without it, it opens the new category's page.
 */
export function CreateCategoryDialog({
  trigger,
  variant = 'primary',
  className,
  onCreated,
}: {
  trigger: ReactNode
  variant?: 'primary' | 'default' | 'ghost'
  className?: string
  onCreated?: (category: Category) => void
}) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
  const [direction, setDirection] = useState<'fwd' | 'back' | null>(null)
  const [name, setName] = useState('')
  const [siteIds, setSiteIds] = useState<number[]>([])
  const [nameMissing, setNameMissing] = useState(false)
  const [sitesMissing, setSitesMissing] = useState(false)
  // Set once createCategory succeeds: if linking its sites then fails, a retry
  // only links them, and never creates a second category.
  const [created, setCreated] = useState<Category | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const stepRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const create = useMutation({
    mutationFn: async () => {
      let category = created
      if (!category) {
        category = await createCategory({ name: name.trim() })
        setCreated(category)
      }
      return setCategorySites(category.id, siteIds)
    },
    onSuccess: (category) => {
      void queryClient.invalidateQueries({ queryKey: ['sites'] })
      setOpen(false)
      if (onCreated) onCreated(category)
      else navigate(`/categories/${category.slug}`)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
    },
  })

  const fieldError =
    create.error instanceof ApiError ? (create.error.fields?.name ?? create.error.message) : null
  const dirty = name.trim() !== '' || siteIds.length > 0

  // Reset when opening rather than closing, so the exit animation shows the dialog as it was.
  const onOpenChange = (next: boolean) => {
    if (next) {
      setStep(1)
      setDirection(null)
      setName('')
      setSiteIds([])
      setNameMissing(false)
      setSitesMissing(false)
      setCreated(null)
      create.reset()
    }
    setOpen(next)
  }

  const goTo = (next: 1 | 2) => {
    flushSync(() => {
      setDirection(next === 2 ? 'fwd' : 'back')
      setStep(next)
    })
    stepRef.current?.querySelector<HTMLElement>('input, button')?.focus({ preventScroll: true })
  }

  const submit = () => {
    if (step === 1) {
      if (!name.trim()) {
        setNameMissing(true)
        nameRef.current?.focus()
        return
      }
      goTo(2)
      return
    }
    if (siteIds.length === 0) {
      setSitesMissing(true)
      return
    }
    create.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant={variant} size="sm" className={className}>
          {trigger}
        </Button>
      </DialogTrigger>
      <DialogContent onInteractOutside={(e) => dirty && e.preventDefault()}>
        <DialogHeader>
          <DialogEyebrow>
            <StepPips steps={['Name', 'Sites']} current={step} />
          </DialogEyebrow>
          <DialogTitle>New category</DialogTitle>
          {step === 1 ? (
            <DialogDescription>
              A category groups similar items and sets which sites Snagr searches for them.
            </DialogDescription>
          ) : null}
        </DialogHeader>
        <form
          className="contents"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <DialogBody>
            <div
              key={step}
              ref={stepRef}
              className={direction === 'fwd' ? 'animate-step-fwd' : direction === 'back' ? 'animate-step-back' : undefined}
            >
              {step === 1 ? (
                <>
                  <Label htmlFor="category-name">Name</Label>
                  <Input
                    ref={nameRef}
                    id="category-name"
                    autoFocus
                    autoComplete="off"
                    placeholder="e.g. Keyboards"
                    aria-invalid={nameMissing || undefined}
                    className="aria-invalid:border-rise/60"
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value)
                      setNameMissing(false)
                    }}
                  />
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="mr-0.5 font-mono text-[11px] text-ink-3">Try:</span>
                    {SUGGESTIONS.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="rounded-[3px] border border-hairline px-[7px] py-0.5 font-mono text-[11px] text-ink-3 transition-colors hover:border-hairline-strong hover:text-ink"
                        onClick={() => {
                          setName(suggestion)
                          setNameMissing(false)
                          nameRef.current?.focus()
                        }}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                  {nameMissing ? (
                    <p role="alert" className="mt-2.5 text-xs text-rise">
                      ⚠ Give it a name.
                    </p>
                  ) : null}
                </>
              ) : (
                <>
                  <p className="mb-3 text-[13.5px] text-ink-2">
                    Where should Snagr look for <b className="font-medium text-ink">{name.trim()}</b>?
                  </p>
                  <SitePicker
                    selected={siteIds}
                    onChange={(ids) => {
                      setSiteIds(ids)
                      if (ids.length > 0) setSitesMissing(false)
                    }}
                  />
                  {sitesMissing ? (
                    <p role="alert" className="mt-2.5 text-xs text-rise">
                      ⚠ Pick at least one site. Snagr needs somewhere to look.
                    </p>
                  ) : (
                    <p className="mt-2.5 text-xs text-ink-3">
                      Pick one or more. You can change them any time from the dashboard or the category page.
                    </p>
                  )}
                  {fieldError ? (
                    <p role="alert" className="mt-1.5 text-xs text-rise">
                      {fieldError}
                    </p>
                  ) : null}
                </>
              )}
            </div>
          </DialogBody>
          <DialogFooter>
            {/* once the category exists a retry only links sites, so a renamed step 1 would be ignored */}
            {step === 2 && !created ? (
              <Button variant="ghost" className="mr-auto" onClick={() => goTo(1)}>
                ← Back
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="max-sm:flex-[2]" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              {step === 1 ? 'Next: sites →' : 'Create category'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
