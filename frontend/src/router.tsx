import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AdminGuard, AuthGuard } from '@/features/auth/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { RegisterPage } from '@/features/auth/RegisterPage'
import { InvitePage } from '@/features/auth/InvitePage'
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
import { EmptyState } from '@/components/ui/empty-state'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  { path: '/invite/:token', element: <InvitePage /> },
  {
    element: <AuthGuard />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/categories/:slug', element: <CategoryPage /> },
      { path: '/items/:id', element: <ItemDetailPage /> },
      { path: '/sites', element: <SitesPage /> },
      { path: '/activity', element: <ActivityPage /> },
      { path: '/activity/:id', element: <JobPage /> },
      // old bookmarks land somewhere: a run no longer exists, but the page
      // that replaced it does
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
        element: <EmptyState title="Page not found" description="This page doesn't exist. Use the navigation to get back on track." />,
      },
    ],
  },
])
