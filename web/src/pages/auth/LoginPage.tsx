import { Lockup } from '@/components/brand'
import { SignIn } from './SignIn'

/** /login: "Log in or sign up" over the dimmed page (a bottom sheet on phones). */
export function LoginPage() {
  return (
    <main className="relative min-h-full bg-bg">
      <div className="flex h-[52px] items-center bg-bg2 px-5 sm:px-8">
        <Lockup height={22} />
      </div>
      <SignIn />
    </main>
  )
}
