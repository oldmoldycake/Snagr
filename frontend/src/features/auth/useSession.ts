import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getInstance, getMe, login, logout, register } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'

export function useSession() {
  return useQuery({
    queryKey: qk.session,
    queryFn: getMe,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 401) && failureCount < 1,
    staleTime: 5 * 60_000,
  })
}

export function useInstance() {
  return useQuery({ queryKey: qk.instance, queryFn: getInstance, staleTime: 5 * 60_000 })
}

export function useLogin() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: login,
    onSuccess: ({ user }) => {
      queryClient.setQueryData(qk.session, user)
      navigate('/', { replace: true })
    },
  })
}

export function useRegister() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: register,
    onSuccess: ({ user }) => {
      queryClient.setQueryData(qk.session, user)
      navigate('/', { replace: true })
    },
  })
}

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
