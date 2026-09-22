import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { enqueueJobs } from '@/api/endpoints'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { JobScope } from '@/api/types'
import { Button, type ButtonProps } from '@/components/ui/button'

/** How long the button holds its receipt before going back to being a button. */
const CONFIRM_MS = 3000

/**
 * Re-read the prices of what is already tracked in a scope. Checks are cheap
 * and finish in seconds, so the button confirms the count it queued and then
 * returns — there is no live state worth showing for work that is over before
 * a sheet could open.
 */
export function CheckPricesButton({
  scope,
  scopeId,
  label,
  ...buttonProps
}: {
  scope: JobScope
  scopeId?: number
  label?: string
} & Omit<ButtonProps, 'onClick' | 'children'>) {
  const queryClient = useQueryClient()
  const [queued, setQueued] = useState<number | null>(null)

  const ask = useMutation({
    mutationFn: () => enqueueJobs({ kind: 'recheck', scope, scope_id: scopeId }),
    onSuccess: (res) => {
      setQueued(res.data.length)
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  useEffect(() => {
    if (queued == null) return
    const t = setTimeout(() => setQueued(null), CONFIRM_MS)
    return () => clearTimeout(t)
  }, [queued])

  if (queued != null) {
    return (
      <Button {...buttonProps} disabled>
        <span aria-hidden className="text-drop">
          ✓
        </span>
        Queued {queued}
      </Button>
    )
  }

  return (
    <Button {...buttonProps} disabled={ask.isPending || buttonProps.disabled} onClick={() => ask.mutate()}>
      <RefreshCw className={ask.isPending ? 'animate-spin' : undefined} />
      {label ?? 'Check prices'}
    </Button>
  )
}
