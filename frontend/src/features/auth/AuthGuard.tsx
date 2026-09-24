import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useSession } from './useSession'
import { AppShell } from '@/components/layout/AppShell'
import { JobsProvider } from '@/features/activity/JobsProvider'

/**
 * Route guard for signed-in pages: sends a visitor without a session to /login
 * (remembering where they were headed) and wraps the rest in the job feed and
 * app shell.
 */
export function AuthGuard() {
  const location = useLocation()
  const { data: user, isLoading, isError } = useSession()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="size-5 animate-spin text-ink-3" />
      </div>
    )
  }

  if (isError || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
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
