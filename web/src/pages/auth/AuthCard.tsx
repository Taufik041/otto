import type { ReactNode } from 'react'
import { Mark } from '@/components/brand'

/** The sign-in screens: a centered card on the secondary background, the mark on top. */
export function AuthCard({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-full flex-col items-center overflow-y-auto bg-bg2 px-4 py-6 sm:px-6 sm:py-12">
      <div className="flex-1" />
      <div className="w-full max-w-[400px] rounded-3xl border border-solid border-hair bg-card px-[22px] py-8 shadow-card animate-pop-slow sm:px-9 sm:py-10">
        <div className="flex justify-center">
          <Mark size={52} />
        </div>
        {children}
      </div>
      <div className="flex-1" />
    </main>
  )
}

export function AuthTitle({ children, tight = false }: { children: ReactNode; tight?: boolean }) {
  return (
    <h1
      className={`mx-0 mt-[22px] text-center text-[28px] font-semibold leading-[1.15] tracking-[-0.02em] ${tight ? 'mb-2.5' : 'mb-7'}`}
    >
      {children}
    </h1>
  )
}

export function Or() {
  return (
    <div className="my-[22px] flex items-center gap-3 text-[13px] text-muted">
      <div className="h-px flex-1 bg-hair" />
      or
      <div className="h-px flex-1 bg-hair" />
    </div>
  )
}

export function Banner({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="mb-5 rounded-xl bg-bad-bg px-3.5 py-2.5 text-[13.5px] text-bad">
      {children}
    </div>
  )
}
