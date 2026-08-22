import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { acceptInvite, validateInvite } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { qk } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AuthLayout } from './AuthLayout'

export function InvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: () => validateInvite(token),
    retry: false,
  })

  const accept = useMutation({
    mutationFn: () => acceptInvite(token, { email: invite.data?.email ?? email, password }),
    onSuccess: ({ user }) => {
      queryClient.setQueryData(qk.session, user)
      navigate('/', { replace: true })
    },
  })

  if (invite.isLoading) {
    return (
      <AuthLayout>
        <div className="flex justify-center py-8">
          <Loader2 className="size-5 animate-spin text-ink-3" />
        </div>
      </AuthLayout>
    )
  }

  if (invite.isError) {
    const expired = invite.error instanceof ApiError && invite.error.status === 410
    return (
      <AuthLayout>
        <h1 className="font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase">
          {expired ? 'Invite expired' : 'Invite not valid'}
        </h1>
        <p className="mt-2 text-[13px] text-ink-2">
          {expired
            ? 'This invite has expired or was already used. Ask your admin for a new one.'
            : 'This invite link is not valid. Check the link or ask your admin for a new invite.'}
        </p>
        <p className="mt-4 text-center text-xs text-ink-3">
          <Link to="/login" className="text-lume hover:underline">
            Back to sign in
          </Link>
        </p>
      </AuthLayout>
    )
  }

  const lockedEmail = invite.data?.email
  const errorMessage = accept.error instanceof ApiError ? accept.error.message : null

  return (
    <AuthLayout>
      <h1 className="font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase">Join Snagr</h1>
      <p className="mt-1 text-xs text-ink-2">You've been invited. Set a password to finish creating your account.</p>

      <form
        className="mt-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          accept.mutate()
        }}
      >
        {errorMessage ? (
          <p role="alert" className="rounded-sm border border-rise/40 bg-rise/10 px-3 py-2 text-xs text-rise">
            {errorMessage}
          </p>
        ) : null}

        <div>
          <Label htmlFor="invite-email">Email</Label>
          <Input
            id="invite-email"
            type="email"
            required
            value={lockedEmail ?? email}
            readOnly={lockedEmail != null}
            className={lockedEmail != null ? 'opacity-60' : undefined}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="invite-password">Password</Label>
          <Input
            id="invite-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <Button type="submit" variant="primary" className="w-full" disabled={accept.isPending}>
          {accept.isPending ? <Loader2 className="animate-spin" /> : null}
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
