import { SignIn } from './auth/SignIn'
import { PublicLayout } from './public/PublicLayout'

/** /request-access: the invite-only form as a page of its own, for direct links. */
export function RequestAccessPage() {
  return (
    <PublicLayout>
      <div className="flex justify-center px-4 pb-[72px] pt-10 sm:px-6 sm:pb-[140px] sm:pt-[88px]">
        <SignIn page initial="invite" />
      </div>
    </PublicLayout>
  )
}
