import { useState } from 'react'
import { api, goToGitHub } from '@/api'
import { messageOf } from '@/api/errors'
import { GitHubIcon } from '@/components/brand'
import { Button } from '@/components/ui/button'

/** "Continue with GitHub": the gateway gives the URL (and sets the state's cookie), then we go. */
export function GitHubSignIn({ onError }: { onError: (message: string) => void }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      variant="dark"
      size="lg"
      className="w-full gap-2.5"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        try {
          await goToGitHub(() => api.githubUrl('signin'))
        } catch (e) {
          onError(messageOf(e))
          setBusy(false)
        }
      }}
    >
      <GitHubIcon size={18} />
      Continue with GitHub
    </Button>
  )
}
