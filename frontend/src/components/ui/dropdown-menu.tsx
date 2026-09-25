import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import { MoreHorizontal } from 'lucide-react'
import { useRef, type ComponentProps, type ComponentPropsWithoutRef, type FocusEvent, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'

/** Dropdown menu root — Radix DropdownMenu.Root. */
export const DropdownMenu = MenuPrimitive.Root
/** Element that opens the menu — Radix DropdownMenu.Trigger. */
export const DropdownMenuTrigger = MenuPrimitive.Trigger

/** The ⋯ button that opens a row's or a shelf's menu; it stays lit while its menu is open. */
export function DropdownMenuMoreTrigger({ label, className }: { label: string; className?: string }) {
  return (
    <MenuPrimitive.Trigger asChild>
      <Button
        variant="ghost"
        size="iconSm"
        aria-label={label}
        className={cn('data-[state=open]:bg-raised data-[state=open]:text-lume', className)}
      >
        <MoreHorizontal />
      </Button>
    </MenuPrimitive.Trigger>
  )
}

/**
 * Slides the highlight plate onto the row Radix just focused. Radix focuses the
 * highlighted item for pointer and keyboard alike, and the content itself when
 * the pointer leaves, so focus is the one signal to follow. The first placement
 * after the plate was off lands in place; only moves between rows slide.
 */
function placePlate(content: HTMLElement, plate: HTMLElement, target: HTMLElement) {
  if (target.getAttribute('role') !== 'menuitem' || target.hasAttribute('data-noplate')) {
    delete plate.dataset.state
    return
  }
  // offsets, not client rects: the panel is still scaling while the first row lights
  let y = 0
  for (let node: HTMLElement | null = target; node && node !== content; ) {
    y += node.offsetTop
    node = node.offsetParent as HTMLElement | null
  }
  const wasOff = plate.dataset.state !== 'on'
  if (wasOff) plate.dataset.instant = ''
  plate.style.setProperty('--y', `${y}px`)
  plate.style.setProperty('--h', `${target.offsetHeight}px`)
  plate.dataset.tone = target.dataset.tone ?? ''
  plate.dataset.state = 'on'
  if (wasOff) {
    void plate.offsetWidth // commit the jump, so restoring transitions doesn't replay it
    delete plate.dataset.instant
  }
}

/**
 * The menu panel — Radix DropdownMenu.Content in a portal. It grows out of its
 * trigger, its rows drop in in turn, and one plate tracks the highlighted row
 * (see "Dropdown menus" in globals.css).
 */
export function DropdownMenuContent({
  className,
  sideOffset = 4,
  onFocus,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof MenuPrimitive.Content>) {
  const plateRef = useRef<HTMLSpanElement>(null)
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={sideOffset}
        collisionPadding={8}
        loop
        onFocus={(e: FocusEvent<HTMLDivElement>) => {
          if (plateRef.current) placePlate(e.currentTarget, plateRef.current, e.target)
          onFocus?.(e)
        }}
        className={cn(
          'menu-panel relative z-50 min-w-36 origin-(--radix-dropdown-menu-content-transform-origin) overflow-hidden rounded-md border border-hairline-strong bg-overlay p-1 shadow-[0_1px_0_rgb(193_255_208/0.05)_inset,0_22px_44px_-14px_rgb(0_0_0/0.75),0_0_0_1px_rgb(0_0_0/0.35)] outline-none',
          'data-[state=open]:animate-menu-in data-[state=closed]:animate-menu-out',
          className,
        )}
        {...props}
      >
        {children}
        <span ref={plateRef} aria-hidden className="menu-plate" />
      </MenuPrimitive.Content>
    </MenuPrimitive.Portal>
  )
}

/**
 * The header that names what the menu acts on — Radix DropdownMenu.Label, so it
 * is read but never focused. `title` gets the display face; `meta` sits beside
 * it; children are extra lines under it.
 */
export function DropdownMenuLabel({
  title,
  meta,
  className,
  children,
  ...props
}: { title?: ReactNode; meta?: ReactNode } & ComponentPropsWithoutRef<typeof MenuPrimitive.Label>) {
  return (
    <MenuPrimitive.Label
      className={cn(
        '-mx-1 -mt-1 mb-1 grid gap-[7px] border-b border-hairline bg-linear-to-b from-[rgb(193_255_208/0.025)] to-transparent px-3 pt-[11px] pb-2.5',
        className,
      )}
      {...props}
    >
      {title != null ? (
        <span className="flex min-w-0 items-baseline gap-2.5">
          <span className="truncate font-display text-[17px] leading-none font-semibold tracking-[0.06em] text-ink uppercase">
            {title}
          </span>
          {meta}
        </span>
      ) : null}
      {children}
    </MenuPrimitive.Label>
  )
}

/**
 * One menu entry — Radix DropdownMenu.Item. The highlight plate paints the
 * highlighted row's ground; `tone="danger"` is for deletes, and tints the plate.
 */
export function DropdownMenuItem({
  className,
  tone,
  ...props
}: { tone?: 'danger' } & ComponentProps<typeof MenuPrimitive.Item>) {
  return (
    <MenuPrimitive.Item
      data-tone={tone}
      className={cn(
        'relative z-[1] flex min-h-8 cursor-default items-center gap-2.5 rounded-sm py-1.5 pr-2 pl-[11px] text-[13px] text-ink-2 outline-none select-none',
        '[&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-ink-3 [&_svg]:transition-colors',
        'data-highlighted:text-ink data-highlighted:[&_svg]:text-lume data-disabled:opacity-50',
        tone === 'danger' && 'text-rise data-highlighted:text-rise [&_svg]:text-rise data-highlighted:[&_svg]:text-rise',
        className,
      )}
      {...props}
    />
  )
}

/** Mono text on a menu row's right edge: a count, a path, a version. */
export function DropdownMenuHint({ className, ...props }: ComponentPropsWithoutRef<'span'>) {
  return <span className={cn('ml-auto font-mono text-[10.5px] whitespace-nowrap text-ink-3 tnum', className)} {...props} />
}

/** Hairline between menu groups — Radix DropdownMenu.Separator. */
export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn('mx-0.5 my-1 h-px bg-hairline', className)} {...props} />
}
