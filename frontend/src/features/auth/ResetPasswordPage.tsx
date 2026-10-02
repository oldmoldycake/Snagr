import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { completePasswordReset, validatePasswordReset } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usePageTitle } from '@/lib/usePageTitle'
import { AuthLayout } from './AuthLayout'
import { NewPasswordInput } from './NewPasswordInput'

/**
 * Password-reset page at /reset/:token, the link an admin issues from the users
 * list: validates the token, then sets the new password. Every sign-in the
 * account had ends, so the user signs in again with the new password.
 */
export function ResetPasswordPage() {
  usePageTitle('Reset password')
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [password, setPassword] = useState('')

  const reset = useQuery({
    queryKey: ['password-reset', token],
    queryFn: () => validatePasswordReset(token),
    retry: false,
  })

  const complete = useMutation({
    mutationFn: () => completePasswordReset(token, { password }),
    meta: { inlineError: true },
    onSuccess: () => {
      // this browser's session, if it had one, was ended with the rest
      queryClient.clear()
      toast.success('Password changed — sign in with the new one')
      navigate('/login', { replace: true })
    },
  })

  if (reset.isLoading) {
    return (
      <AuthLayout>
        <div className="flex justify-center py-8">
          <Loader2 className="size-5 animate-spin text-ink-3" />
        </div>
      </AuthLayout>
    )
  }

  if (reset.isError) {
    const expired = reset.error instanceof ApiError && reset.error.status === 410
    return (
      <AuthLayout>
        <h1 className="font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase">
          {expired ? 'Link expired' : 'Link not valid'}
        </h1>
        <p className="mt-2 text-[14px] text-ink-2">
          {expired
            ? 'This reset link has expired or was already used. Ask your admin for a new one.'
            : 'This reset link is not valid. Check the link or ask your admin for a new one.'}
        </p>
        <p className="mt-4 text-center text-xs text-ink-3">
          <Link to="/login" className="text-lume hover:underline">
            Back to sign in
          </Link>
        </p>
      </AuthLayout>
    )
  }

  const errorMessage = complete.error instanceof ApiError ? complete.error.message : null

  return (
    <AuthLayout>
      <h1 className="font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase">Reset password</h1>
      <p className="mt-1 text-xs text-ink-2">Choose a new password. This signs the account out everywhere.</p>

      <form
        className="mt-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          complete.mutate()
        }}
      >
        {errorMessage ? (
          <p role="alert" className="rounded-sm border border-rise/40 bg-rise/10 px-3 py-2 text-xs text-rise">
            {errorMessage}
          </p>
        ) : null}

        <div>
          <Label htmlFor="reset-email">Email</Label>
          <Input
            id="reset-email"
            type="email"
            autoComplete="username"
            readOnly
            className="text-ink-2"
            value={reset.data?.email ?? ''}
          />
        </div>
        <div>
          <Label htmlFor="reset-password">New password</Label>
          <NewPasswordInput id="reset-password" value={password} onChange={setPassword} />
        </div>

        <Button type="submit" variant="primary" className="w-full" disabled={complete.isPending}>
          {complete.isPending ? <Loader2 className="animate-spin" /> : null}
          Set password
        </Button>
      </form>
    </AuthLayout>
  )
}
