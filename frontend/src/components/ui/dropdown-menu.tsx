import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import type { ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/cn'

/** Dropdown menu root — Radix DropdownMenu.Root. */
export const DropdownMenu = MenuPrimitive.Root
/** Element that opens the menu — Radix DropdownMenu.Trigger. */
export const DropdownMenuTrigger = MenuPrimitive.Trigger

/** The menu panel — Radix DropdownMenu.Content in a portal. */
export function DropdownMenuContent({
  className,
  sideOffset = 4,
  ...props
}: ComponentPropsWithoutRef<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-36 rounded-md border border-hairline bg-overlay p-1 shadow-xl',
          className,
        )}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
}

/** One menu entry — Radix DropdownMenu.Item. */
export function DropdownMenuItem({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof MenuPrimitive.Item>) {
  return (
    <MenuPrimitive.Item
      className={cn(
        'flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] text-ink-2 outline-none select-none',
        'data-highlighted:bg-raised data-highlighted:text-ink [&_svg]:size-3.5',
        className,
      )}
      {...props}
    />
  )
}

/** Hairline between menu groups — Radix DropdownMenu.Separator. */
export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn('my-1 h-px bg-hairline', className)} {...props} />
}
