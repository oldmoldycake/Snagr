import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { getInstance, getMe, login, logout, register } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'

/** The signed-in user; a 401 is the answer "signed out", so it is never retried. */
export function useSession() {
  return useQuery({
    queryKey: qk.session,
    queryFn: getMe,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 401) && failureCount < 1,
    staleTime: 5 * 60_000,
  })
}

/** Instance-wide facts the UI adapts to: open registration, SSO, which features are on. */
export function useInstance() {
  return useQuery({ queryKey: qk.instance, queryFn: getInstance, staleTime: 5 * 60_000 })
}

/** Where a signed-in visitor on /login should land; see `returnPath`. */
export function useReturnTo(): string {
  return returnPath(useLocation().state)
}

/**
 * The page AuthGuard bounced the visitor from (its `state.from`), else the
 * dashboard. Only an in-app path is honoured, so `//host` can't send them
 * off-site.
 */
export function returnPath(state: unknown): string {
  const from: unknown = (state as { from?: unknown } | null)?.from
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') ? from : '/'
}

/** Sign in, seed the session cache from the response and go back to where the visitor was headed. */
export function useLogin() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const returnTo = useReturnTo()
  return useMutation({
    mutationFn: login,
    meta: { inlineError: true },
    onSuccess: ({ user }) => {
      queryClient.setQueryData(qk.session, user)
      navigate(returnTo, { replace: true })
    },
  })
}

/** Create an account, seed the session cache from the response and go to the dashboard. */
export function useRegister() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: register,
    meta: { inlineError: true },
    onSuccess: ({ user }) => {
      queryClient.setQueryData(qk.session, user)
      navigate('/', { replace: true })
    },
  })
}

/** Sign out and drop every cached query, so the next user sees none of this one's data. */
export function useLogout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear()
      navigate('/login', { replace: true })
    },
  })
}
