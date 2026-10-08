import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AdminGuard, AuthGuard } from '@/features/auth/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { RegisterPage } from '@/features/auth/RegisterPage'
import { InvitePage } from '@/features/auth/InvitePage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { CategoryPage } from '@/features/categories/CategoryPage'
import { ItemDetailPage } from '@/features/items/ItemDetailPage'
import { SitesPage } from '@/features/sites/SitesPage'
import { ActivityPage } from '@/features/activity/ActivityPage'
import { JobPage } from '@/features/activity/JobPage'
import { ReviewQueuePage } from '@/features/vision/ReviewQueuePage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { ApiSettingsPage } from '@/features/settings/ApiSettingsPage'
import { AdminUsersPage } from '@/features/settings/AdminUsersPage'
import { NotFound } from '@/components/ui/not-found'
import { RouteError } from '@/components/ui/route-error'

/**
 * Every page in the app; the public auth pages sit outside the guard, admin
 * pages behind a second one. Two error boundaries: the root's catches a crash
 * outside the app shell (an auth page, or the shell itself) on a bare page;
 * the inner one keeps the shell and its navigation around a page that crashed.
 */
export const router = createBrowserRouter([
  {
    errorElement: <RouteError fullPage />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
      { path: '/invite/:token', element: <InvitePage /> },
      { path: '/reset/:token', element: <ResetPasswordPage /> },
      {
        element: <AuthGuard />,
        children: [
          {
            errorElement: <RouteError />,
            children: [
              { path: '/', element: <DashboardPage /> },
              { path: '/categories/:slug', element: <CategoryPage /> },
              { path: '/items/:id', element: <ItemDetailPage /> },
              { path: '/sites', element: <SitesPage /> },
              { path: '/activity', element: <ActivityPage /> },
              { path: '/activity/:id', element: <JobPage /> },
              // /runs links in old bookmarks still land somewhere: jobs live on the
              // Activity page
              { path: '/runs', element: <Navigate to="/activity" replace /> },
              { path: '/runs/:id', element: <Navigate to="/activity" replace /> },
              { path: '/review', element: <ReviewQueuePage /> },
              { path: '/settings', element: <SettingsPage /> },
              { path: '/settings/api', element: <ApiSettingsPage /> },
              {
                element: <AdminGuard />,
                children: [{ path: '/settings/users', element: <AdminUsersPage /> }],
              },
              {
                path: '*',
                element: <NotFound title="Page not found" description="This page doesn't exist." />,
              },
            ],
          },
        ],
      },
    ],
  },
])
