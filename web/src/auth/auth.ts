import { useEffect, useState, useSyncExternalStore } from 'react'
import { useSearchParams } from 'react-router'
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

/** An email sign-up that hasn't opened its confirmation link: it sees "Confirm your email"
 *  instead of the app. (Older gateways leave email_verified out: confirmed.) */
export function needsConfirmation(user: Me): boolean {
  return user.email !== null && user.email_verified === false
}

/** A safe in-app path from ?next=, else "/". */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

/** Why a trip to GitHub failed, in plain words: the gateway's ?error=<code> (and ?login=), shown
 *  in the sign-in dialog or in Settings → GitHub. A code this doesn't know gets the generic line. */
export function githubErrorMessage(code: string | null, login: string | null, where: 'signin' | 'settings'): string | null {
  if (!code) return null
  const signin = where === 'signin'
  switch (code) {
    case 'github_already_linked':
      return `This GitHub account${login ? ` (@${login})` : ''} is already linked to a different Otto account. Sign in with GitHub to use that account, or unlink it there first.`
    case 'github_account_mismatch':
      return `Your Otto account is already connected to GitHub${login ? ` as @${login}` : ''}. Disconnect it in Settings → GitHub first to connect a different account.`
    case 'installation_taken':
      return 'This GitHub App installation is connected to a different Otto account. Ask its owner to disconnect it, or install the app on another account or org.'
    case 'github_email_in_use':
      return 'An Otto account already uses this email. Log in with your email, then connect GitHub from Settings.'
    case 'invite_only':
      return 'Otto is invite-only right now, so it can’t make a new account for this GitHub account.'
    case 'paused':
      return 'Otto isn’t taking new accounts right now. Try again later.'
    case 'state_invalid':
      return 'That GitHub sign-in expired or was started in another browser. Try again.'
    case 'access_denied':
      return signin ? 'GitHub sign-in was cancelled. Try again, or use your email.' : 'Connecting GitHub was cancelled. Nothing changed.'
    case 'github_unavailable':
      return "GitHub didn't answer as expected. Try again in a minute."
    default:
      return signin ? "GitHub sign-in didn't finish. Try again, or use your email." : "Connecting GitHub didn't finish. Try again."
  }
}

/** The ?error=<code> (and ?login=) a GitHub callback came back with, read once: they leave the
 *  URL right away, so a reload or a shared link doesn't show the message again. */
export function useCallbackError(): { code: string | null; login: string | null } {
  const [params, setParams] = useSearchParams()
  const [found] = useState(() => ({ code: params.get('error'), login: params.get('login') }))
  useEffect(() => {
    if (!found.code) return
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        next.delete('error')
        next.delete('login')
        return next
      },
      { replace: true },
    )
  }, [found, setParams])
  return found
}
