import type { ReactNode } from 'react'

/** Chromeless night screen: reticle rings behind a centered lockup + card. */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-1/2 size-[720px] -translate-x-1/2 -translate-y-[54%] rounded-full"
        style={{
          background:
            'radial-gradient(circle, transparent 0 179px, rgb(193 255 208 / 0.05) 179px 180px, transparent 180px 269px, rgb(193 255 208 / 0.04) 269px 270px, transparent 270px 359px, rgb(193 255 208 / 0.03) 359px 360px, transparent 360px)',
        }}
      >
        <span className="absolute top-0 left-1/2 h-full w-px bg-[rgb(193_255_208_/_0.04)]" />
        <span className="absolute top-1/2 left-0 h-px w-full bg-[rgb(193_255_208_/_0.04)]" />
      </div>

      <div className="relative w-full max-w-sm">
        <div className="mb-7 text-center">
          <span aria-hidden className="block text-3xl leading-none text-lume">
            ⌖
          </span>
          <span className="mt-1.5 block font-display text-[40px] leading-none font-bold tracking-[0.14em] text-ink">
            SNAGR
          </span>
          <p className="mt-2.5 font-mono text-[11px] tracking-[0.04em] text-ink-3">
            Set a target. The agent hunts all night.
          </p>
        </div>
        <div className="rounded-lg border border-hairline bg-surface p-6">{children}</div>
      </div>
    </div>
  )
}
