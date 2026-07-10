import { useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/cn'
import { AuthLayout } from './AuthLayout'
import { useInstance, useLogin, useSession } from './useSession'

const MOCKS_ON = import.meta.env.VITE_USE_MOCKS === 'true'

export function LoginPage() {
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const login = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [searchParams] = useSearchParams()

  if (user) return <Navigate to="/" replace />

  const errorMessage =
    login.error instanceof ApiError
      ? login.error.message
      : login.error
        ? 'Something went wrong — try again'
        : searchParams.get('error') === 'sso_failed'
          ? 'SSO sign-in failed — try again or use your password'
          : null

  return (
    <AuthLayout>
      <h1 className="font-display text-base font-semibold text-ink">Sign in</h1>

      {MOCKS_ON ? (
        <div className="mt-3 rounded-sm border border-accent/40 bg-accent/10 px-3 py-2">
          <p className="text-xs text-ink-2">
            Mock API is on — demo account:{' '}
            <code className="font-mono text-accent">demo@snagr.dev</code> /{' '}
            <code className="font-mono text-accent">snagr</code>
          </p>
          <Button
            variant="primary"
            size="sm"
            className="mt-2 w-full"
            disabled={login.isPending}
            onClick={() => login.mutate({ email: 'demo@snagr.dev', password: 'snagr' })}
          >
            {login.isPending ? <Loader2 className="animate-spin" /> : null}
            Explore with the demo account
          </Button>
        </div>
      ) : null}

      <form
        className="mt-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          login.mutate({ email, password })
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <Button type="submit" variant="primary" className="w-full" disabled={login.isPending}>
          {login.isPending ? <Loader2 className="animate-spin" /> : null}
          Sign in
        </Button>
      </form>

      {instance?.oidc_provider_name ? (
        <div className="mt-4">
          <div className="flex items-center gap-2">
            <span className="h-px flex-1 bg-hairline" />
            <span className="text-xs text-ink-3">or</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>
          <a
            href="/api/auth/oidc/login"
            className={cn(buttonVariants({ variant: 'default' }), 'mt-3 w-full')}
          >
            Sign in with {instance.oidc_provider_name}
          </a>
        </div>
      ) : null}

      {instance?.registration_open ? (
        <p className="mt-4 text-center text-xs text-ink-3">
          New here?{' '}
          <Link to="/register" className="text-accent hover:underline">
            Create an account
          </Link>
        </p>
      ) : (
        <p className="mt-4 text-center text-xs text-ink-3">Need an account? Ask your admin for an invite.</p>
      )}
    </AuthLayout>
  )
}
