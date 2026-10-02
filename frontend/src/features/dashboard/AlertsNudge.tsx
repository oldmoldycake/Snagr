import { useState } from 'react'
import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { useTargetAlertGap } from '@/features/settings/alertGap'

// Dismissal is a per-browser convenience, so storage failures (private mode,
// blocked site data, a full quota) are ignored rather than surfaced: the
// nudge shows again, and the item page still warns beside Notify.
function wasDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) != null
  } catch {
    return false
  }
}

function rememberDismissed(key: string) {
  try {
    localStorage.setItem(key, '1')
  } catch {
    // see wasDismissed()
  }
}

/**
 * The guide's last step, once there are items to be alerted about: while no
 * channel would carry an at-target alert, says so and points to Settings.
 * Dismissing it is remembered per browser and per user
 * (`snagr:alerts-nudge:<user id>`).
 */
export function AlertsNudge({ userId, className }: { userId: number; className?: string }) {
  const key = `snagr:alerts-nudge:${userId}`
  const gap = useTargetAlertGap()
  const [dismissed, setDismissed] = useState(() => wasDismissed(key))

  if (gap == null || dismissed) return null
  const dismiss = () => {
    rememberDismissed(key)
    setDismissed(true)
  }

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-warn/40 bg-warn/[0.07] py-2 pr-2 pl-4',
        className,
      )}
    >
      <p className="min-w-0 flex-1 basis-64 text-[14px] text-ink-2">
        <span aria-hidden className="text-warn">
          ⚠
        </span>{' '}
        {gap === 'no-channels' ? (
          <>
            <b className="font-semibold text-warn">Alerts go nowhere yet.</b> Add a channel and Snagr tells you when
            an item reaches its target.
          </>
        ) : (
          <>
            <b className="font-semibold text-warn">Alerts go nowhere.</b> None of your channels is on for at-target
            alerts.
          </>
        )}
      </p>
      <div className="flex items-center gap-1">
        <Link to="/settings" className={buttonVariants({ variant: 'warn', size: 'sm' })}>
          Choose where alerts go
        </Link>
        <Button variant="ghost" size="iconSm" aria-label="Dismiss this reminder" onClick={dismiss}>
          <X />
        </Button>
      </div>
    </div>
  )
}
