import { passwordStrength, strengthCopy } from '@/utils/password'

/** Four bars and a sentence, as in the design's sign-up. */
export function StrengthMeter({ password }: { password: string }) {
  const s = passwordStrength(password)
  const { tone, message } = strengthCopy(s)
  const color = `var(--${tone})`
  return (
    <>
      <span className="mt-0.5 flex gap-1" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="h-1 flex-1 rounded-full transition-[background] duration-[250ms]"
            style={{ background: i < Math.max(1, s) ? color : 'var(--line)' }}
          />
        ))}
      </span>
      <span className="text-[13px]" style={{ color }}>
        {message}
      </span>
    </>
  )
}
