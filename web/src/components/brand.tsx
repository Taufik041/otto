import lockupDark from '@/assets/logo/logo-lockup-dark.svg'
import lockupLight from '@/assets/logo/logo-lockup-light.svg'
import markDark from '@/assets/logo/logo-mark-dark.svg'
import markLight from '@/assets/logo/logo-mark-light.svg'
import { cn } from '@/utils/cn'

/** The loop mark; both files are in the page and CSS shows the one for the theme (no flash). */
export function Mark({ size, className, label }: { size: number; className?: string; label?: string }) {
  const alt = label ?? ''
  return (
    <span className={cn('inline-flex shrink-0', className)} style={{ width: size, height: size }}>
      <img src={markLight} alt={alt} width={size} height={size} className="only-light block" />
      <img src={markDark} alt={alt} width={size} height={size} className="only-dark block" />
    </span>
  )
}

/** The mark and the "otto" wordmark, for the sidebar header (about 22px tall). */
export function Lockup({ height = 22, className }: { height?: number; className?: string }) {
  const width = (height * 184.7) / 64
  return (
    <span className={cn('inline-flex shrink-0', className)} style={{ width, height }}>
      <img src={lockupLight} alt="Otto" width={width} height={height} className="only-light block" />
      <img src={lockupDark} alt="Otto" width={width} height={height} className="only-dark block" />
    </span>
  )
}

const GH =
  'M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.74.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z'

/** GitHub's mark (lucide has no brand icons). */
export function GitHubIcon({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <path d={GH} fill="currentColor" />
    </svg>
  )
}

/** The small outlined "Beta" beside the wordmark (the landing nav, the sign-in dialog, the sidebar). */
export function BetaPill({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-5 shrink-0 items-center rounded-full border border-solid border-line px-[7px] text-[11px] font-medium leading-none tracking-[.02em] text-muted',
        className,
      )}
    >
      Beta
    </span>
  )
}
