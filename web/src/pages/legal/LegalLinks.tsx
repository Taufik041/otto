import { Link } from 'react-router'
import { cn } from '@/utils/cn'

/** Terms · Privacy · Acceptable use, quietly (the Settings sidebar and its phone root). */
export function LegalLinks({ className }: { className?: string }) {
  return (
    <nav aria-label="Legal" className={cn('flex flex-wrap gap-x-3 gap-y-1 text-[13px]', className)}>
      <Link to="/legal/terms" className="text-muted hover:text-text">Terms</Link>
      <Link to="/legal/privacy" className="text-muted hover:text-text">Privacy</Link>
      <Link to="/legal/acceptable-use" className="text-muted hover:text-text">Acceptable use</Link>
    </nav>
  )
}
