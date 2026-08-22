import type { ReactNode } from 'react'
import { Masthead } from './Masthead'
import { ActivitySheet } from '@/features/runs/ActivitySheet'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Masthead />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1040px] px-6 py-8 md:py-10">{children}</div>
      </main>
      <ActivitySheet />
    </div>
  )
}
