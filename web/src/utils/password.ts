/** The design's four-bar strength meter: 0–4. The gateway only requires 8 characters. */
export function passwordStrength(pw: string): number {
  let s = 0
  if (pw.length >= 8) s++
  if (/\d/.test(pw)) s++
  if (/[A-Z]/.test(pw) || /[^A-Za-z0-9]/.test(pw)) s++
  if (pw.length >= 12) s++
  return s
}

export const MIN_PASSWORD = 8

export function strengthCopy(s: number): { tone: 'bad' | 'warn' | 'ok'; message: string } {
  if (s <= 1) return { tone: 'bad', message: 'Too weak. Use 8 or more characters with a number.' }
  if (s === 2) return { tone: 'warn', message: 'Okay. Add a symbol or make it longer.' }
  return { tone: 'ok', message: 'Strong password.' }
}
