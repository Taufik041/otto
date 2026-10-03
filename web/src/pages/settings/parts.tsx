import type { ComponentProps, ReactNode } from 'react'
import { messageOf } from '@/api/errors'
import { cn } from '@/utils/cn'

export function Card({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('rounded-[18px] border border-solid border-line', className)} {...props} />
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="mx-1 mb-2.5 text-[13px] font-semibold text-muted">{children}</div>
}

export function Row({ children, first = false }: { children: ReactNode; first?: boolean }) {
  return (
    <div
      className="flex flex-wrap items-center gap-3 px-5 py-4"
      style={{ borderTop: first ? 'none' : '1px solid var(--hair)' }}
    >
      {children}
    </div>
  )
}

export function Loading() {
  return <div className="h-32" aria-busy="true" />
}

export function Problem({ error }: { error: unknown }) {
  return (
    <p role="alert" className="m-0 text-[15px] text-bad">
      {messageOf(error)}
    </p>
  )
}
