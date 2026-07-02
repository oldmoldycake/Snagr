import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)

export async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== 'true') return
  await worker.start({
    onUnhandledRequest: 'bypass',
  })
  // eslint-disable-next-line no-console
  console.info('[snagr] Mock API enabled — sign in with demo@snagr.dev / snagr')
}
