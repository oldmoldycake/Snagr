import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useRef, type ComponentPropsWithoutRef, type HTMLAttributes } from 'react'
import { swipeCloses } from '@/components/ui/sheetSwipe'
import { cn } from '@/lib/cn'
import { focusMovedElsewhere } from '@/lib/focus'

/** Modal dialog root — Radix Dialog.Root. */
export const Dialog = DialogPrimitive.Root
/** Element that opens the dialog — Radix Dialog.Trigger. */
export const DialogTrigger = DialogPrimitive.Trigger
/** Element that closes the dialog — Radix Dialog.Close. */
export const DialogClose = DialogPrimitive.Close

/**
 * Field-card modal over a dimmed overlay, with a close button — Radix
 * Dialog.Content in a portal. Lay it out as DialogHeader → DialogBody →
 * DialogFooter: only the body scrolls, so the footer's buttons stay in view.
 * Anchored near the top rather than centred, so a growing body only pushes
 * downward; under `sm` it becomes a bottom sheet that its grab handle swipes closed.
 *
 * Pass `dismissible={false}` while it shows something that can't be shown
 * again, like a new API token: Escape and clicks outside then do nothing and
 * the ✕ and the handle are hidden, so the only way out is the dialog's own button.
 */
export function DialogContent({
  className,
  children,
  dismissible = true,
  onOpenAutoFocus,
  onCloseAutoFocus,
  onEscapeKeyDown,
  onInteractOutside,
  ...props
}: ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { dismissible?: boolean }) {
  // Radix only returns focus to a DialogTrigger, but most dialogs here are
  // opened from state by a plain button or a menu item. Remember what had focus
  // on open and hand it back on close. A menu item unmounts with its menu, so
  // stand in the button that opened the menu (it names the menu in aria-controls).
  const returnFocusTo = useRef<HTMLElement | null>(null)
  // The open state lives in Radix's Root, out of reach here, so a swipe on the
  // handle closes the sheet by pressing the ✕.
  const close = useRef<HTMLButtonElement>(null)

  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgb(5_8_6/0.72)] data-[state=closed]:animate-overlay-out data-[state=open]:animate-overlay-in" />
      <DialogPrimitive.Content
        className={cn(
          'fixed top-[max(8vh,2rem)] left-1/2 z-50 grid max-h-[min(720px,calc(100dvh-4rem))] w-[calc(100%-2rem)] max-w-[480px] -translate-x-1/2 origin-top grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden',
          'rounded-lg border border-hairline-strong bg-overlay shadow-[0_24px_64px_-16px_rgb(0_0_0/0.8)] focus:outline-none',
          'data-[state=closed]:animate-dialog-out data-[state=open]:animate-dialog-in',
          'max-sm:top-auto max-sm:bottom-0 max-sm:left-0 max-sm:max-h-[92dvh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:grid-rows-[auto_auto_minmax(0,1fr)_auto] max-sm:rounded-t-xl max-sm:rounded-b-none',
          'max-sm:data-[state=closed]:animate-sheet-down max-sm:data-[state=open]:animate-sheet-up',
          'max-sm:transition-[translate] max-sm:duration-200 max-sm:ease-sheet',
          className,
        )}
        onOpenAutoFocus={(event) => {
          const active = document.activeElement
          const menu = active?.closest('[role="menu"]')
          const opener = menu?.id ? document.querySelector(`[aria-controls="${CSS.escape(menu.id)}"]`) : active
          returnFocusTo.current =
            opener instanceof HTMLElement && !(event.currentTarget as Node).contains(opener) ? opener : null
          onOpenAutoFocus?.(event)
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event)
          if (focusMovedElsewhere(event.currentTarget)) event.preventDefault()
          if (event.defaultPrevented || !returnFocusTo.current?.isConnected) return
          event.preventDefault()
          returnFocusTo.current.focus()
        }}
        onEscapeKeyDown={(event) => {
          onEscapeKeyDown?.(event)
          if (!dismissible) event.preventDefault()
        }}
        onInteractOutside={(event) => {
          onInteractOutside?.(event)
          if (!dismissible) event.preventDefault()
        }}
        {...props}
      >
        <SheetHandle onSwipe={dismissible ? () => close.current?.click() : undefined} />
        {children}
        {dismissible ? (
          <DialogPrimitive.Close
            ref={close}
            className="tap-target absolute top-3.5 right-3.5 grid size-7 place-items-center rounded-sm text-ink-3 hover:bg-raised hover:text-ink"
            aria-label="Close"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

/**
 * A sheet's grab handle, on a strip across the sheet's top. Dragging the strip
 * pulls the sheet down under the finger through its `translate`, which the
 * enter and exit animations leave alone, so a sheet that closes slides out from
 * where it was let go. Letting go calls `onSwipe` when `swipeCloses` judges the
 * swipe meant to close, or springs the sheet back. Without `onSwipe` the strip
 * keeps its room but shows no handle.
 */
function SheetHandle({ onSwipe }: { onSwipe?: () => void }) {
  const press = useRef<{ id: number; sheet: HTMLElement; y: number; at: number } | null>(null)
  const springBack = (sheet: HTMLElement) => {
    sheet.style.transition = ''
    sheet.style.translate = ''
  }

  return (
    <div
      aria-hidden
      className="touch-none pt-2 pb-3 sm:hidden"
      onPointerDown={(event) => {
        const sheet = event.currentTarget.parentElement
        if (!onSwipe || !sheet || press.current || event.button !== 0) return
        event.currentTarget.setPointerCapture(event.pointerId)
        sheet.style.transition = 'none'
        press.current = { id: event.pointerId, sheet, y: event.clientY, at: event.timeStamp }
      }}
      onPointerMove={(event) => {
        const p = press.current
        if (p?.id !== event.pointerId) return
        p.sheet.style.translate = `0 ${Math.max(0, event.clientY - p.y)}px`
      }}
      onPointerUp={(event) => {
        const p = press.current
        if (p?.id !== event.pointerId) return
        press.current = null
        if (onSwipe && swipeCloses(event.clientY - p.y, event.timeStamp - p.at, p.sheet.offsetHeight)) onSwipe()
        else springBack(p.sheet)
      }}
      onPointerCancel={(event) => {
        const p = press.current
        if (p?.id !== event.pointerId) return
        press.current = null
        springBack(p.sheet)
      }}
    >
      <div className={cn('mx-auto h-1 w-8 rounded-full bg-hairline-strong', !onSwipe && 'invisible')} />
    </div>
  )
}

/**
 * Top band holding the eyebrow, title and description; its right padding
 * clears the close button. On a sheet the grab handle's strip above it takes
 * most of its top padding, so the handle is a bigger target for a thumb.
 */
export function DialogHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('relative border-b border-hairline px-5 pt-[18px] pr-12 pb-3.5 max-sm:pt-1.5', className)} {...props} />
}

/** Small mono label above the title, naming what the dialog acts on. */
export function DialogEyebrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('mb-2 font-mono text-[12px] tracking-[0.16em] text-ink-3 uppercase', className)}
      {...props}
    />
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
        'font-display text-[20px] font-semibold tracking-[0.08em] text-ink uppercase',
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
      className={cn('mt-1.5 text-[14px] text-ink-2', className)}
      {...props}
    />
  )
}

/** The dialog's fields — the one part that scrolls when the dialog is taller than the screen. */
export function DialogBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('overflow-y-auto overscroll-contain px-5 py-4', className)} {...props} />
}

/**
 * Bottom band for the action buttons: Back (`mr-auto`), then Cancel, then the
 * primary, always rightmost. Under `sm` the buttons share the row, and the
 * primary takes `max-sm:flex-[2]` at the call site.
 */
export function DialogFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-center justify-end gap-2 border-t border-hairline bg-black/10 px-5 py-3',
        'max-sm:pb-[calc(0.75rem+env(safe-area-inset-bottom))] max-sm:*:h-10 max-sm:*:flex-1',
        className,
      )}
      {...props}
    />
  )
}
