import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { RouterProvider } from 'react-router-dom'
import { Toaster, toast } from 'sonner'
import { ApiError } from '@/api/client'
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

const queryClient = new QueryClient({
  // A failed save always says so: a toast, unless the component shows the
  // server's reason in place. Nothing a user clicks fails silently.
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
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
      refetchOnWindowFocus: false,
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
