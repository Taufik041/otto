import { Dialog as D } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/utils/cn'

// shadcn's Dialog, restyled: the design's scrim, a 22px-radius card, calm pop-in.
export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({
  className,
  children,
  ...props
}: ComponentProps<typeof D.Content> & { children: ReactNode }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-[100] bg-scrim animate-fade" />
      <D.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-[101] w-[calc(100%-32px)] max-w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-[22px] border border-solid border-hair bg-card p-6 text-text shadow-pop outline-none',
          className,
        )}
        {...props}
      >
        <div className="animate-pop">{children}</div>
      </D.Content>
    </D.Portal>
  )
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof D.Title>) {
  return <D.Title className={cn('m-0 text-[19px] font-semibold tracking-[-0.01em]', className)} {...props} />
}

export function DialogDescription({ className, ...props }: ComponentProps<typeof D.Description>) {
  return <D.Description className={cn('mt-1.5 mb-0 text-[15px] text-muted text-pretty', className)} {...props} />
}

export function DialogFooter({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('mt-6 flex flex-wrap justify-end gap-2.5', className)} {...props} />
}
