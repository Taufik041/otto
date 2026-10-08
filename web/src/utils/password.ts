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

/** The meter's sentence. The only rule is the gateway's (auth.strong_password): at least
 *  MIN_PASSWORD characters; the rest is advice. */
export function strengthCopy(pw: string): { tone: 'bad' | 'warn' | 'ok'; message: string } {
  if (pw.length < MIN_PASSWORD) return { tone: 'bad', message: `Use at least ${MIN_PASSWORD} characters.` }
  if (passwordStrength(pw) <= 2) return { tone: 'warn', message: 'Okay. A longer password is stronger.' }
  return { tone: 'ok', message: 'Strong password.' }
}
