import * as SwitchPrimitive from '@radix-ui/react-switch'
import type { ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/cn'

export function Switch({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        'inline-flex h-4.5 w-8 shrink-0 items-center rounded-full border border-hairline-strong bg-well transition-colors',
        'data-[state=checked]:border-lume/50 data-[state=checked]:bg-lume-glow',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'block size-3 translate-x-0.5 rounded-full bg-ink-3 transition-transform',
          'data-[state=checked]:translate-x-4 data-[state=checked]:bg-lume',
        )}
      />
    </SwitchPrimitive.Root>
  )
}
