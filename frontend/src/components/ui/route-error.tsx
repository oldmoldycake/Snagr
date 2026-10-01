import { Link, useRouteError } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { usePageTitle } from '@/lib/usePageTitle'
import { Button, buttonVariants } from './button'

/**
 * What a route shows when rendering it throws, in place of React Router's
 * developer stack-trace screen. Nothing here can be retried in place — the
 * tree that threw would throw again — so the ways out are a full reload and
 * the dashboard. `fullPage` is the root's version, for a crash outside the
 * app shell (an auth page, or the shell itself).
 */
export function RouteError({ fullPage = false }: { fullPage?: boolean }) {
  const error = useRouteError()
  usePageTitle('Something broke')
  return (
    <div className={cn(fullPage && 'flex min-h-screen items-center justify-center p-4')}>
      <div
        role="alert"
        className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-rise/40 px-6 py-12 text-center"
      >
        <span aria-hidden className="font-display text-2xl text-rise">
          ⚠
        </span>
        <p className="text-sm font-medium text-ink">Something broke on this page</p>
        <p className="max-w-sm text-[13px] text-ink-2">
          This is a bug in Snagr, not a problem with your data. Reloading usually clears it.
        </p>
        {error instanceof Error ? <p className="max-w-sm font-mono text-[11px] text-ink-3">{error.message}</p> : null}
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => window.location.reload()}>
            Reload
          </Button>
          <Link to="/" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
            Go to dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
