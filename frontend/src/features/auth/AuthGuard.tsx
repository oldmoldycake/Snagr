import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { isSignedOut } from '@/api/client'
import { useSession } from './useSession'
import { AppShell } from '@/components/layout/AppShell'
import { ErrorState } from '@/components/ui/error-state'
import { JobsProvider } from '@/features/activity/JobsProvider'

/**
 * Route guard for signed-in pages: sends a visitor without a session to /login
 * (remembering where they were headed) and wraps the rest in the job feed and
 * app shell. Only a 401 means no session: when Snagr can't answer, the visitor
 * is told so, with Retry, rather than sent to a sign-in form that can't work
 * either; a failed refetch keeps the user already signed in.
 */
export function AuthGuard() {
  const location = useLocation()
  const { data: user, error, isLoading, isFetching, refetch } = useSession()

  if (isLoading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-ink-3" />
      </div>
    )
  }

  if (isSignedOut(error)) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />
  }

  if (!user) {
    return (
      <div className="flex h-dvh items-center justify-center p-4">
        <ErrorState title="Couldn't reach Snagr" error={error} onRetry={() => void refetch()} retrying={isFetching} />
      </div>
    )
  }

  return (
    <JobsProvider>
      <AppShell>
        <Outlet />
      </AppShell>
    </JobsProvider>
  )
}

/** Route guard for admin-only pages. Renders inside AuthGuard, so session exists. */
export function AdminGuard() {
  const { data: user } = useSession()
  if (user?.role !== 'admin') return <Navigate to="/settings" replace />
  return <Outlet />
}
