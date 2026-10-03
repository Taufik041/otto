import { useState } from 'react'
import { cn } from '@/utils/cn'
import { initials } from '@/utils/format'

/** The user's GitHub avatar, or their initials on the inverse color when there isn't one. */
export function Avatar({
  name,
  email,
  url,
  size = 32,
  className,
}: {
  name: string | null | undefined
  email?: string | null
  url?: string | null
  size?: number
  className?: string
}) {
  const [broken, setBroken] = useState(false)
  const style = { width: size, height: size, fontSize: Math.round(size * 0.36) }
  if (url && !broken) {
    return (
      <img
        src={url}
        alt=""
        style={style}
        onError={() => setBroken(true)}
        className={cn('shrink-0 rounded-full bg-sel object-cover', className)}
      />
    )
  }
  return (
    <span
      aria-hidden="true"
      style={style}
      className={cn('flex shrink-0 items-center justify-center rounded-full bg-inv font-semibold text-inv-text', className)}
    >
      {initials(name, email)}
    </span>
  )
}
