import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AuthLayout } from './AuthLayout'
import { useInstance, useRegister } from './useSession'

export function RegisterPage() {
  const { data: instance, isLoading } = useInstance()
  const register = useRegister()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (!isLoading && instance && !instance.registration_open) {
    return <Navigate to="/login" replace />
  }

  const errorMessage = register.error instanceof ApiError ? register.error.message : null

  return (
    <AuthLayout>
      <h1 className="font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase">Create your account</h1>
      <p className="mt-1 text-xs text-ink-2">
        The first account on a fresh instance becomes the admin. After that, sign-up stays open
        while the instance allows it — otherwise new users join by invite.
      </p>

      <form
        className="mt-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          register.mutate({ email, password })
        }}
      >
        {errorMessage ? (
          <p role="alert" className="rounded-sm border border-rise/40 bg-rise/10 px-3 py-2 text-xs text-rise">
            {errorMessage}
          </p>
        ) : null}

        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <Button type="submit" variant="primary" className="w-full" disabled={register.isPending}>
          {register.isPending ? <Loader2 className="animate-spin" /> : null}
          Create account
        </Button>
      </form>

      <p className="mt-4 text-center text-xs text-ink-3">
        Already set up?{' '}
        <Link to="/login" className="text-lume hover:underline">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
