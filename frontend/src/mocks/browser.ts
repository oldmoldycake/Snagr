import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

/**
 * The MSW service worker serving every mock handler. Only ever loaded via the
 * dynamic import in main.tsx when VITE_USE_MOCKS=true, so msw and the fixture
 * store stay out of the real bundle.
 */
export const worker = setupWorker(...handlers)
