import { createBrowserRouter } from 'react-router-dom'
import { AdminGuard, AuthGuard } from '@/features/auth/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { RegisterPage } from '@/features/auth/RegisterPage'
import { InvitePage } from '@/features/auth/InvitePage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { CategoryPage } from '@/features/categories/CategoryPage'
import { ItemDetailPage } from '@/features/items/ItemDetailPage'
import { SitesPage } from '@/features/sites/SitesPage'
import { RunsPage } from '@/features/runs/RunsPage'
import { RunDetailPage } from '@/features/runs/RunDetailPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
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
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/:id', element: <RunDetailPage /> },
      { path: '/settings', element: <SettingsPage /> },
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
