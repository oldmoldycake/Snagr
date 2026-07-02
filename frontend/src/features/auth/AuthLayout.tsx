import type { ReactNode } from 'react'

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span aria-hidden className="text-2xl leading-none text-drop">
            ⌖
          </span>
          <span className="font-display text-xl font-bold tracking-wide text-ink">SNAGR</span>
        </div>
        <div className="rounded-lg border border-hairline bg-surface p-6">{children}</div>
        <p className="mt-4 text-center text-xs text-ink-3">
          Self-hosted price tracking. Set a target, let the agent watch, snag the deal.
        </p>
      </div>
    </div>
  )
}
