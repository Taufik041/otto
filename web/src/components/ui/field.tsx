import { AlertTriangle } from 'lucide-react'
import { useId, type ComponentProps, type ReactNode } from 'react'
import { cn } from '@/utils/cn'

/** The auth and settings inputs: a 46px field, 12px radius; red with a soft ring on error. */
export function Field({
  label,
  aside,
  error,
  note,
  className,
  ...input
}: ComponentProps<'input'> & { label: string; aside?: ReactNode; error?: ReactNode; note?: ReactNode }) {
  const id = useId()
  const msg = `${id}-msg`
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <span className="flex items-baseline">
        <label htmlFor={id} className="flex-1 text-[13px] font-medium">
          {label}
        </label>
        {aside}
      </span>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || note ? msg : undefined}
        className={cn(
          'h-[46px] rounded-xl border border-solid bg-bg px-3.5 text-base text-text outline-none transition-[border-color,box-shadow]',
          error ? 'border-bad shadow-[0_0_0_3px_var(--bad-bg)]' : 'border-line focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-bg)]',
        )}
        {...input}
      />
      {error ? (
        <span id={msg} role="alert" className="flex items-start gap-1.5 text-[13px] text-bad">
          <AlertTriangle size={14} strokeWidth={1.8} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </span>
      ) : note ? (
        <span id={msg}>{note}</span>
      ) : null}
    </div>
  )
}
