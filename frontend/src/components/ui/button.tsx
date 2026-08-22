import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm font-mono font-medium tracking-[0.06em] uppercase transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'border border-hairline-strong bg-transparent text-ink-2 hover:border-ink-3 hover:text-ink',
        primary: 'bg-lume font-semibold text-[#1a1208] hover:bg-lume-deep',
        snag: 'bg-drop font-semibold text-[#10150e] hover:brightness-110',
        ghost: 'text-ink-2 hover:bg-raised hover:text-ink',
        destructive: 'bg-rise/10 text-rise border border-rise/40 hover:bg-rise/20',
      },
      size: {
        default: 'h-8 px-3 text-xs',
        sm: 'h-7 px-2 text-[11px]',
        icon: 'h-8 w-8',
        iconSm: 'h-7 w-7',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
