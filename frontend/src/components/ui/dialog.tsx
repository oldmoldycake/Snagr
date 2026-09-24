import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ComponentPropsWithoutRef, HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Modal dialog root — Radix Dialog.Root. */
export const Dialog = DialogPrimitive.Root
/** Element that opens the dialog — Radix Dialog.Trigger. */
export const DialogTrigger = DialogPrimitive.Trigger
/** Element that closes the dialog — Radix Dialog.Close. */
export const DialogClose = DialogPrimitive.Close

/**
 * Centered modal panel over a dimmed overlay, with a close button — Radix
 * Dialog.Content in a portal.
 */
export function DialogContent({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=open]:fade-in" />
      <DialogPrimitive.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2',
          'rounded-lg border border-hairline bg-raised p-5 shadow-2xl focus:outline-none',
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute top-4 right-4 -m-2 rounded-sm p-2 text-ink-3 hover:text-ink"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

/** Dialog heading — Radix Dialog.Title, which also labels the dialog for screen readers. */
export function DialogTitle({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn(
        'font-display text-[17px] font-semibold tracking-[0.08em] text-ink uppercase',
        className,
      )}
      {...props}
    />
  )
}

/** Supporting text under the title — Radix Dialog.Description. */
export function DialogDescription({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      className={cn('mt-1 text-[13px] text-ink-2', className)}
      {...props}
    />
  )
}

/** Right-aligned row for the dialog's action buttons. */
export function DialogFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mt-5 flex justify-end gap-2', className)} {...props} />
}
