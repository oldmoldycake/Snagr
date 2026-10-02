import { useState, type ComponentProps } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { enqueueJobs, listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { JobCreateRequest } from '@/api/types'
import type { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { listAllItems } from '@/features/items/allItems'
import { plannedHunts } from './huntScope'
import { huntReceipt } from './lines'

type HuntTarget = Omit<JobCreateRequest, 'kind'>

/** Above this many hunts, one press asks before queueing them. */
const CONFIRM_HUNTS_ABOVE = 10

/**
 * Hunt now, for whichever scope the caller names. Each caller holds its own
 * request, so only the control that was pressed shows it waiting. Most of
 * what it queues waits its turn rather than starting, and a button that just
 * stops spinning says nothing, so a toast says what was queued.
 *
 * `mutate` queues at once. `ask` is for a control whose scope can fan out: a
 * category or a site is a hunt per item, and every hunt adds to the AI
 * provider's bill, so it counts them first and, above CONFIRM_HUNTS_ABOVE,
 * leaves the decision to the ConfirmDialog the caller renders from `confirm`.
 */
export function useHuntNow() {
  const queryClient = useQueryClient()
  // kept after the dialog closes, so its text holds through the exit animation
  const [asking, setAsking] = useState<{ target: HuntTarget; hunts: number } | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const hunt = useMutation({
    mutationFn: (target: HuntTarget) => enqueueJobs({ kind: 'hunt', ...target }),
    onSuccess: (res) => {
      setConfirmOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      if (res.data.length === 0) toast.warning(huntReceipt(res.data))
      else toast.success(huntReceipt(res.data))
    },
  })
  const count = useMutation({
    mutationFn: async (target: HuntTarget) => {
      const [items, categories] = await Promise.all([
        queryClient.fetchQuery({ queryKey: qk.items(), queryFn: () => listAllItems() }),
        queryClient.fetchQuery({ queryKey: qk.categories, queryFn: listCategories }),
      ])
      return plannedHunts(target, items.data, categories.data)
    },
    onSuccess: (hunts, target) => {
      if (hunts <= CONFIRM_HUNTS_ABOVE) {
        hunt.mutate(target)
        return
      }
      setAsking({ target, hunts })
      setConfirmOpen(true)
    },
  })

  const confirm: ComponentProps<typeof ConfirmDialog> = {
    open: confirmOpen,
    onOpenChange: setConfirmOpen,
    title: `Queue ${asking?.hunts} hunts?`,
    description:
      "Each hunt has Snagr search one site for one item, and each adds to your AI provider's bill. Most wait their turn in the queue.",
    confirmLabel: `Queue ${asking?.hunts} hunts`,
    confirmVariant: 'primary',
    onConfirm: () => {
      if (asking) hunt.mutate(asking.target)
    },
    pending: hunt.isPending,
  }

  return {
    ...hunt,
    isPending: hunt.isPending || count.isPending,
    ask: (target: HuntTarget) => (target.scope === 'item' ? hunt.mutate(target) : count.mutate(target)),
    confirm,
  }
}
