import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'bg-raised text-ink border border-hairline hover:bg-overlay',
        primary: 'bg-accent text-white hover:bg-accent/85',
        snag: 'bg-drop/15 text-drop border border-drop/40 hover:bg-drop/25',
        ghost: 'text-ink-2 hover:bg-raised hover:text-ink',
        destructive: 'bg-rise/10 text-rise border border-rise/40 hover:bg-rise/20',
      },
      size: {
        default: 'h-8 px-3 text-[13px]',
        sm: 'h-7 px-2 text-xs',
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
