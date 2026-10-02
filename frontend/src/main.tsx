import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { RouterProvider } from 'react-router-dom'
import { Toaster, toast } from 'sonner'
import { ApiError, isSignedOut } from '@/api/client'
import { qk } from '@/api/queries'
import { TooltipProvider } from '@/components/ui/tooltip'
import { router } from '@/router'

import '@/styles/globals.css'

// Dynamic import so msw + fixtures are only fetched (and only bundled into a
// lazy chunk) when mocks are on; real deployments never load them.
async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== 'true') return
  const { worker } = await import('@/mocks/browser')
  await worker.start({ onUnhandledRequest: 'bypass' })
  // eslint-disable-next-line no-console
  console.info('[snagr] Mock API enabled — sign in with demo@snagr.dev / snagr')
}

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: {
      /**
       * The component renders an ApiError's message itself (a form's alert, a
       * confirm dialog's error), so only a request that never reached Snagr toasts.
       */
      inlineError?: boolean
    }
  }
}

/**
 * A 401 that reaches the cache already survived `api`'s refresh-and-retry, so
 * the refresh token has expired too: drop everything this session cached and
 * send the visitor to sign in, coming back to where they were. Only a visitor
 * the cache still thinks is signed in is sent: a refused login or the signed-out
 * /me on the login page is that page's to show. The cache is cleared first so
 * LoginPage doesn't find the old user and bounce straight back.
 */
function endExpiredSession(error: Error): void {
  if (!isSignedOut(error)) return
  if (queryClient.getQueryData(qk.session) === undefined) return
  const { pathname, search, hash } = router.state.location
  queryClient.clear()
  void router.navigate('/login', { replace: true, state: { from: pathname + search + hash } })
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: endExpiredSession }),
  // A failed save always says so: a toast, unless the component shows the
  // server's reason in place. Nothing a user clicks fails silently.
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      endExpiredSession(error)
      if (error instanceof ApiError) {
        if (!mutation.meta?.inlineError) toast.error(error.message)
      } else {
        toast.error("Couldn't reach Snagr — check your connection and try again")
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      // Lists are what a tab left open overnight shows, so they catch up when
      // it is looked at again. Everything else waits for the live feed or its
      // own staleTime: a detail page's charts refetching on every alt-tab
      // would redraw under the reader for nothing.
      refetchOnWindowFocus: (query) => query.queryKey[1] === 'list' || query.queryKey[0] === 'dashboard',
    },
  },
})

enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <RouterProvider router={router} />
        </TooltipProvider>
        <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: '#16211a', border: '1px solid rgba(193,255,208,0.09)', color: '#e9f1e9' } }} />
        <ReactQueryDevtools initialIsOpen={false} />
      </QueryClientProvider>
    </StrictMode>,
  )
})
