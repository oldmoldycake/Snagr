import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/cn'

/** Side-panel root — Radix Dialog.Root. */
export const Sheet = DialogPrimitive.Root
/** Element that opens the sheet — Radix Dialog.Trigger. */
export const SheetTrigger = DialogPrimitive.Trigger
/** Element that closes the sheet — Radix Dialog.Close. */
export const SheetClose = DialogPrimitive.Close
/** Sheet heading — Radix Dialog.Title. */
export const SheetTitle = DialogPrimitive.Title
/** Sheet supporting text — Radix Dialog.Description. */
export const SheetDescription = DialogPrimitive.Description

/** Full-height panel sliding in from the left or right edge — Radix Dialog.Content in a portal. */
export function SheetContent({
  side = 'right',
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { side?: 'left' | 'right' }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <DialogPrimitive.Content
        className={cn(
          'fixed top-0 z-50 flex h-full w-full max-w-[420px] flex-col border-hairline bg-raised pb-[env(safe-area-inset-bottom)] shadow-2xl focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out',
          side === 'right'
            ? 'right-0 border-l data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right'
            : 'left-0 border-r data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left',
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute top-3.5 right-4 -m-2 rounded-sm p-2 text-ink-3 hover:text-ink"
          aria-label="Close panel"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
