import { DropdownMenu as Menu } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/utils/cn'

// shadcn's DropdownMenu, restyled to the design's menus: a card with a hairline border, 14-16px
// radius, the pop shadow, 14.5px rows with a muted icon.
export const DropdownMenu = Menu.Root
export const DropdownMenuTrigger = Menu.Trigger
export const DropdownMenuGroup = Menu.Group

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-[200px] rounded-[14px] border border-solid border-line bg-card p-1.5 text-text shadow-pop outline-none animate-pop',
          className,
        )}
        {...props}
      />
    </Menu.Portal>
  )
}

export function DropdownMenuItem({
  className,
  variant = 'default',
  ...props
}: ComponentProps<typeof Menu.Item> & { variant?: 'default' | 'danger' }) {
  return (
    <Menu.Item
      data-slot="dropdown-menu-item"
      className={cn(
        'flex w-full cursor-pointer select-none items-center gap-2.5 rounded-[9px] px-3 py-[9px] text-left text-[14.5px] outline-none',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0',
        variant === 'danger'
          ? 'text-bad data-[highlighted]:bg-bad-bg'
          : 'text-text data-[highlighted]:bg-hover [&_svg]:text-muted',
        className,
      )}
      {...props}
    />
  )
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof Menu.Label>) {
  return <Menu.Label className={cn('px-3 pb-2 pt-2.5 text-[12.5px] text-muted', className)} {...props} />
}

export function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof Menu.Separator>) {
  return <Menu.Separator className={cn('mx-2 my-1 h-px bg-hair', className)} {...props} />
}
