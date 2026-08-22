import * as SelectPrimitive from '@radix-ui/react-select'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/cn'

/**
 * Styled single-value select over Radix. Options-array API — every select in
 * the app is a flat list, so composability isn't worth the boilerplate.
 */
export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  className,
}: {
  value: string | undefined
  onValueChange: (value: string) => void
  options: readonly { value: string; label: string }[]
  placeholder?: string
  ariaLabel: string
  className?: string
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={ariaLabel}
        className={cn(
          'flex h-8 items-center justify-between gap-2 rounded-sm border border-hairline-strong bg-well px-2.5 text-[13px] text-ink',
          'focus:border-lume/60 focus:outline-none data-[placeholder]:text-ink-3',
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon>
          <ChevronDown className="size-3.5 text-ink-3" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 min-w-[var(--radix-select-trigger-width)] rounded-md border border-hairline bg-overlay p-1 shadow-xl"
        >
          <SelectPrimitive.Viewport>
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                className="flex cursor-default items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-[13px] text-ink-2 outline-none select-none data-highlighted:bg-raised data-highlighted:text-ink"
              >
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator>
                  <Check className="size-3.5 text-lume" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}
