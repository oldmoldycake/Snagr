import { Loader2, Search } from 'lucide-react'
import type { JobScope } from '@/api/types'
import { Button, type ButtonProps } from '@/components/ui/button'
import { useInstance } from '@/features/auth/useSession'
import { useJobs } from './JobsProvider'

/**
 * Ask the hunter to look for listings, scoped. While a hunt for that scope is
 * already live the button says so and opens the sheet instead of queueing
 * another — the queue would dedupe it anyway, and "Hunting…" is the honest
 * answer to "hunt now". With hunting switched off for the instance it is
 * disabled and says why: the backend would answer 409 hunting_disabled.
 */
export function HuntButton({
  scope,
  scopeId,
  label,
  ...buttonProps
}: {
  scope: JobScope
  scopeId?: number
  label?: string
} & Omit<ButtonProps, 'onClick' | 'children'>) {
  const { enqueue, isEnqueuing, setPanelOpen, liveHuntFor } = useJobs()
  const live = liveHuntFor(scope, scopeId)
  const huntingOff = useInstance().data?.hunt_enabled === false

  if (live) {
    return (
      <Button {...buttonProps} onClick={() => setPanelOpen(true)}>
        <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-lume" />
        Hunting…
      </Button>
    )
  }

  return (
    <Button
      {...buttonProps}
      disabled={huntingOff || isEnqueuing || buttonProps.disabled}
      title={huntingOff ? 'Hunting is paused by the operator' : buttonProps.title}
      onClick={() => enqueue({ kind: 'hunt', scope, scope_id: scopeId })}
    >
      {isEnqueuing ? <Loader2 className="animate-spin" /> : <Search />}
      {label ?? 'Hunt now'}
    </Button>
  )
}
