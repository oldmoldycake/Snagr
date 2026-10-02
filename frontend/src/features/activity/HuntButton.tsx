import { Loader2, Search } from 'lucide-react'
import type { JobScope } from '@/api/types'
import { Button, type ButtonProps } from '@/components/ui/button'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { useInstance } from '@/features/auth/useSession'
import { useJobs } from './JobsProvider'
import { useHuntNow } from './useHuntNow'

/**
 * Ask the hunter to look for listings, scoped. While a hunt for that scope is
 * already live the button says so and opens the sheet instead of queueing
 * another — the queue would dedupe it anyway, and "Hunting…" is the honest
 * answer to "hunt now". With hunting switched off for the instance it is
 * disabled and says why: the backend would answer 409 hunting_disabled. It is
 * aria-disabled rather than disabled, because a disabled button takes no
 * pointer or focus events and its reason could never be shown.
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
  const { setPanelOpen, liveHuntFor } = useJobs()
  const huntNow = useHuntNow()
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

  if (huntingOff) {
    return (
      <SimpleTooltip content="Hunting is turned off on this server" asChild>
        <Button {...buttonProps} aria-disabled>
          <Search />
          {label ?? 'Hunt now'}
        </Button>
      </SimpleTooltip>
    )
  }

  return (
    <Button
      {...buttonProps}
      disabled={huntNow.isPending || buttonProps.disabled}
      onClick={() => huntNow.mutate({ scope, scope_id: scopeId })}
    >
      {huntNow.isPending ? <Loader2 className="animate-spin" /> : <Search />}
      {label ?? 'Hunt now'}
    </Button>
  )
}
