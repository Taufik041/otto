import { useSyncExternalStore } from 'react'
import { client } from '@/api'
import type { AuthStatus } from '@/api/client'
import type { Me } from '@/api/types'

export type AuthStatusSettled = Exclude<AuthStatus, 'loading'>

export function useAuth() {
  return useSyncExternalStore(client.subscribe, client.getState)
}

/** The signed-in user; only for pages behind RequireAuth. */
export function useMe(): Me {
  const { user } = useAuth()
  if (!user) throw new Error('useMe outside RequireAuth')
  return user
}

// Where to land after a trip to GitHub. GitHub's callback ends a sign-in or link at /auth/callback
// and an install at /settings/github; this remembers which page started it (this tab only).
const RETURN_KEY = 'otto.return'

export function rememberReturn(path: string) {
  try {
    sessionStorage.setItem(RETURN_KEY, path)
  } catch {
    // storage blocked: land on the default page
  }
}

export function takeReturn(): string | null {
  try {
    const v = sessionStorage.getItem(RETURN_KEY)
    sessionStorage.removeItem(RETURN_KEY)
    return v && v.startsWith('/') && !v.startsWith('//') ? v : null
  } catch {
    return null
  }
}

export function peekReturn(): string | null {
  try {
    return sessionStorage.getItem(RETURN_KEY)
  } catch {
    return null
  }
}

// Onboarding is offered once per account on this browser, after its first sign-in.
const onboardedKey = (uid: string) => `otto.onboarded.${uid}`

export function isOnboarded(uid: string): boolean {
  try {
    return localStorage.getItem(onboardedKey(uid)) === '1'
  } catch {
    return true
  }
}

export function markOnboarded(uid: string) {
  try {
    localStorage.setItem(onboardedKey(uid), '1')
  } catch {
    // fine: worst case it's offered again
  }
}

/** A new account (made in the last 15 minutes) that hasn't seen onboarding here. */
export function needsOnboarding(user: Me, now = Date.now()): boolean {
  return now - Date.parse(user.created_at) < 15 * 60_000 && !isOnboarded(user.id)
}

/** A safe in-app path from ?next=, else "/". */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

/** GitHub's ?github_error= (e.g. access_denied when the user cancels) in plain words. */
export function githubErrorMessage(code: string | null): string | null {
  if (!code) return null
  return code === 'access_denied'
    ? 'GitHub sign-in was cancelled. Try again, or use your email.'
    : "GitHub sign-in didn't finish. Try again, or use your email."
}
