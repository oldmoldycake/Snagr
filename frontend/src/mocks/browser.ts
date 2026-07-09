import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

// Only ever loaded via the dynamic import in main.tsx when VITE_USE_MOCKS=true,
// so msw and the fixture store stay out of the real bundle.
export const worker = setupWorker(...handlers)
