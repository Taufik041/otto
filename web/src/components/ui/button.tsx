import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/utils/cn'

// shadcn's Button, restyled to the design: pills. Blue is the brand, not the button: the primary
// pill is black in light and white in dark, the rest are outlined. Hover is instant (no transition).
export const buttonVariants = cva(
  'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap border-0 disabled:opacity-50 disabled:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'rounded-full bg-inv text-inv-text hover:text-inv-text hover:opacity-[.82]',
        outline: 'rounded-full border border-solid border-line bg-transparent text-text hover:bg-hover',
        danger: 'rounded-full border border-solid border-bad bg-transparent text-bad hover:bg-bad-bg',
        dangerSolid: 'rounded-full bg-bad text-white hover:opacity-90',
        ghost: 'rounded-[10px] bg-transparent text-text hover:bg-sel',
        link: 'bg-transparent p-0 text-accent hover:text-accent-h',
      },
      size: {
        xl: 'h-[50px] px-7 text-[17px]',
        lg: 'h-12 px-6 text-base',
        md: 'h-10 px-5 text-[15px]',
        sm: 'h-[34px] px-4 text-sm',
        icon: 'size-9 p-0',
        none: '',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export function Button({
  className,
  variant,
  size,
  asChild = false,
  type = 'button',
  ...props
}: ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button'
  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}
