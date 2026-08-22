import { Loader2, Play } from 'lucide-react'
import type { RunScope } from '@/api/types'
import { Button, type ButtonProps } from '@/components/ui/button'
import { isRunActive, useRunEvents } from './RunEventsProvider'

/**
 * Run-the-agent button, scoped. While any run is active every RunButton
 * becomes "Running…" and opens the activity panel instead of triggering.
 */
export function RunButton({
  scope,
  scopeId,
  label,
  ...buttonProps
}: {
  scope: RunScope
  scopeId?: number
  label?: string
} & Omit<ButtonProps, 'onClick' | 'children'>) {
  const { activeRun, trigger, isTriggering, setPanelOpen } = useRunEvents()
  const active = isRunActive(activeRun)

  if (active) {
    return (
      <Button {...buttonProps} onClick={() => setPanelOpen(true)}>
        <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-lume" />
        Running…
      </Button>
    )
  }

  return (
    <Button
      {...buttonProps}
      disabled={isTriggering || buttonProps.disabled}
      onClick={() => trigger({ scope, scope_id: scopeId })}
    >
      {isTriggering ? <Loader2 className="animate-spin" /> : <Play />}
      {label ?? 'Run agent'}
    </Button>
  )
}
