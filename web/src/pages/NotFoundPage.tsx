import { Link } from 'react-router'
import { Mark } from '@/components/brand'
import { PublicLayout } from './public/PublicLayout'

/** Any path the app doesn't have. The mark turns once, slowly (not with reduced motion). */
export function NotFoundPage() {
  return (
    <PublicLayout>
      <main className="flex min-h-[70vh] flex-col items-center justify-center px-6 py-12 text-center">
        <Mark size={72} className="animate-[otto-once_2.6s_cubic-bezier(.45,0,.2,1)_.5s_1_both]" />
        <div className="mt-7 font-mono text-[13px] text-ter">404</div>
        <h1 className="m-0 mt-2 text-[36px] font-normal leading-[1.06] tracking-[-0.03em] text-balance sm:text-[48px]">
          This page took a wrong turn.
        </h1>
        <p className="m-0 mt-3 text-base text-muted">The link may be old, or the page moved.</p>
        <Link
          to="/"
          className="mt-7 inline-flex h-[42px] items-center rounded-full bg-inv px-[22px] text-base text-inv-text hover:text-inv-text hover:opacity-[.82]"
        >
          Go home
        </Link>
      </main>
    </PublicLayout>
  )
}
